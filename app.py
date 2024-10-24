import logging, json, time, dataclasses, typing, hashlib, urllib, pytest
from fasthtml.common import *
from shad4fast import *
from tractor import connect_tractor

# re https://www.creative-tim.com/twcomponents/component/slack-clone-1
# re https://systemdesign.one/slack-architecture/

# TODO: figure ouf if timestamps resolution is good enough
# TODO: support 1 on 1 channels
# TODO: figure out distinction between 1 on 1 and "private" channels
# TODO: switch to cursor based pagination for messages
# TODO: make message list scrolling work
# TODO: figure out socket authentication

login_redir = RedirectResponse('/login', status_code=303)
def check_auth(req, sess):
    mid, wid = sess.get('mid', None), sess.get('wid', None)
    # If the session key is not there, it redirects to the login page.
    if not mid or not wid: return login_redir

    try:
        req.scope['m'], req.scope['w'] = members[int(mid)], workspaces[int(wid)]
    except NotFoundError: return login_redir

    # `xtra` is part of the MiniDataAPI spec. It adds a filter to queries and DDL statements,
    # to ensure that the user can only see/edit their own todos.
    # todos.xtra(name=auth)

bware = Beforeware(check_auth, skip=[r'/favicon\.ico', r'/static/.*', r'.*\.css', '/login', '/healthcheck'])

app = FastHTMLWithLiveReload(debug=True, hdrs=[
    ShadHead(tw_cdn=True),
    Script(src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js", defer=True),
], exts="ws", before=bware)
rt = app.route

logging.basicConfig(format="%(asctime)s - %(message)s",datefmt="🧵 %d-%b-%y %H:%M:%S",level=logging.DEBUG,handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

def get_image_url(email: str, s=250, d="https://www.example.com/default.jpg") -> str:
    email_hash, query_params = hashlib.sha256(email.lower().encode('utf-8')).hexdigest(), urllib.parse.urlencode({'d': d, 's': str(s)})
    return f"https://www.gravatar.com/avatar/{email_hash}?{query_params}"

# socket connections socket_id -> send
connections: Dict[str, typing.Awaitable] = {}

MESSAGE_HISTORY_PAGE_SIZE = 40

@dataclass(kw_only=True)
class TsRec: created_at: int = dataclasses.field(default_factory=lambda: int(time.time() * 1000))

@dataclass(kw_only=True)
class User(TsRec): id: int; name: str; email: str; image_url: str; is_account_enabled: bool = True
@dataclass(kw_only=True)
class Workspace(TsRec): id: int; name: str
@dataclass(kw_only=True)
class Channel(TsRec):
    id: int; name: str; workspace_id: int; is_direct: bool = False; is_private: bool = False

    @property
    def last_message_ts(self) -> Optional[int]:
        try:
            return next(db.execute(f"""SELECT created_at FROM channel_message WHERE channel={self.id} ORDER BY created_at DESC LIMIT 1"""))[0]
        except StopIteration: return None

@dataclass(kw_only=True)
class ChannelForMember:
    channel_name: str; channel_id: int; member_id: int; has_unread_messages: bool

    @staticmethod
    def from_channel_member(m: 'ChannelMember') -> 'ChannelForMember':
        c = channels[m.channel]
        last_message_ts = c.last_message_ts

        if last_message_ts is None: has_unread_messages = False
        else:
            seen = channel_message_seen_indicators(where=f"channel_id={c.id} AND member_id={m.member}")
            print(f">>>>>>>>>> seen: {seen}")
            seen = seen[0] if len(seen) > 0 else None
            if not seen: has_unread_messages = True
            else: has_unread_messages = c.last_message_ts > seen.last_seen_ts

        return ChannelForMember(channel_id=c.id, channel_name=c.name, member_id=m.member, has_unread_messages=has_unread_messages)
    
    def mark_all_as_read(self) -> 'ChannelForMember':
        channel = channels[self.channel_id]
        seen = channel_message_seen_indicators(where=f"channel_id={channel.id} AND member_id={self.member_id}")
        seen = seen[0] if len(seen) > 0 else None
        if seen:
            seen.last_seen_ts = channel.last_message_ts
            channel_message_seen_indicators.update(seen)
        else:
            channel_message_seen_indicators.insert(ChannelMessageSeenIndicator(channel_id=channel.id, member_id=self.member_id, last_seen_ts=channel.last_message_ts))
        
        return ChannelForMember.from_channel_member(channel_members(where=f"channel={self.channel_id} and member={self.member_id}")[0])

@dataclass(kw_only=True)
class ChannelMessageSeenIndicator:
    channel_id: int; member_id: int; last_seen_ts: int

    @staticmethod
    def update_seen_indicator(channel_id: int, member_id: int, last_seen_ts: int):
        seen = channel_message_seen_indicators(where=f"channel_id={channel_id} AND member_id={member_id}")
        if len(seen) == 0:
            channel_message_seen_indicators.insert(ChannelMessageSeenIndicator(channel_id=channel_id, member_id=member_id, last_seen_ts=last_seen_ts))
        else:
            channel_message_seen_indicators.update(seen[0].id, last_seen_ts=last_seen_ts)

@dataclass(kw_only=True)
class Member(TsRec):
    id: int; user_id: int; workspace_id: int
    @property
    def name(self) -> str: return users[self.user_id].name
    @property
    def image_url(self) -> str: return users[self.user_id].image_url

@dataclass(kw_only=True)
class ChannelMember(TsRec): channel: int; member: int
@dataclass(kw_only=True)
class ChannelMessage(TsRec):
    id: int; channel: int; sender: int; message: str
    
    @staticmethod
    def with_ctx(m: 'ChannelMessage') -> 'ChannelMessageWCtx':
        return ChannelMessageWCtx(*next(db.execute(f"""
            SELECT id, created_at, message, u_name, u_image_url, c_id, c_name
            FROM messages_w_ctx WHERE id={m.id}
        """)))


@dataclass
class ChannelMessageWCtx:
    id: int; created_at: int; message: str; u_name: str; u_image_url: str; c_id: int; c_name: str

    @staticmethod
    def latest(cid: int, offset: int = 0) -> Tuple[List['ChannelMessageWCtx'], int]:
        return list(map(lambda args: ChannelMessageWCtx(*args), db.execute(f"""
            SELECT id, created_at, message, u_name, u_image_url, c_id, c_name
            FROM messages_w_ctx WHERE c_id={cid} ORDER BY created_at DESC LIMIT {MESSAGE_HISTORY_PAGE_SIZE} OFFSET {offset}
        """)))[::-1], offset + MESSAGE_HISTORY_PAGE_SIZE
    
    @staticmethod
    def by_id(message_id: int) -> 'ChannelMessageWCtx':
        return ChannelMessageWCtx(*next(db.execute(f"""
            SELECT id, created_at, message, u_name, u_image_url, c_id, c_name
            FROM messages_w_ctx WHERE id={message_id}
        """)))

@dataclass(kw_only=True)
class Socket(TsRec): sid: str; mid: int

@dataclass
class Command:
    cmd: str

    @staticmethod
    def from_json(cmd: str, data: str) -> 'Command':
        if cmd == "ping": return PingCommand(cmd=cmd, **json.loads(data))
        raise ValueError(f"Invalid command: {cmd}")

@dataclass
class PingCommand(Command): cid: int

@dataclass
class ChannelPlaceholder: members: List[Member]

def get_direct_message_channels(member: Member) -> List[Union[ChannelForMember | ChannelPlaceholder]]:
    # get other members in the workspace
    other_members = members(where=f"workspace_id=(select workspace_id from member where id={member.id}) and id != {member.id}")
    return [ChannelPlaceholder(members=[member, m]) for m in other_members]

def setup_database(test=False):
    global db
    global users, workspaces, channels, members, channel_members, channel_messages, channel_message_seen_indicators, sockets

    db = database('./data/data.db') if not test else database(':memory:')

    users = db.create(User, pk="id")
    workspaces = db.create(Workspace, pk="id")
    # TODO: figure out why foreign key are not enforced 
    channels = db.create(Channel, pk="id", foreign_keys=[("workspace_id", "workspace", "id")])
    # TODO: figure out why foreign key are not enforced 
    members = db.create(Member, pk="id", foreign_keys=[("user_id", "user", "id"), ("workspace_id", "workspace", "id")])
    channel_members = db.create(ChannelMember, pk=("channel", "member"), foreign_keys=[("channel", "channel", "id"), ("member", "member", "id")])
    channel_messages = db.create(ChannelMessage, pk="id", foreign_keys=[("channel", "channel", "id"), ("sender", "user", "id")])
    channel_message_seen_indicators = db.create(ChannelMessageSeenIndicator, pk=("channel_id", "member_id"), foreign_keys=[("channel_id", "channel", "id"), ("member_id", "member", "id")])
    sockets =  db.create(Socket, pk="sid", foreign_keys=[("mid", "member", "id")])

    if not db["messages_w_ctx"].exists():
        db.create_view("messages_w_ctx", """
            select channel_message.id as id, channel_message.created_at as created_at, channel_message.message as message, user.name as u_name, user.image_url as u_image_url,
                channel.id as c_id, channel.name as c_name
            from channel_message
            join member on sender=member.id
            join user on member.user_id=user.id
            join channel on channel_message.channel=channel.id                            
        """)

    if workspaces.count == 0: workspaces.insert(Workspace(name="The Bakery"))
    if channels.count == 0:
        channels.insert(Channel(name="general", workspace_id=1))
        channels.insert(Channel(name="random", workspace_id=1))

    # setup triggers 
    db.conn.execute(f"""CREATE TRIGGER IF NOT EXISTS update_last_seen_message_ts AFTER INSERT ON channel_message
        BEGIN
            INSERT INTO channel_message_seen_indicator(channel_id, member_id, last_seen_ts) VALUES(new.channel, new.sender, new.created_at)
                ON CONFLICT(channel_id, member_id) DO UPDATE SET last_seen_ts=new.created_at;
        END""")

    if not test: connect_tractor(app, db.conn)

setup_database()

async def ws_send_to_member(member_id: int, data):
    s = sockets(where=f"mid={member_id}")[0]
    logger.debug(f"sockets {s}")
    # send message to each socket
    logger.debug(f"sending message to {s.sid} {connections[s.sid]}")
    await connections[s.sid](data)

## UI

@patch
def __ft__(self: Workspace): return Div('👨‍🏭', Strong(self.name))

@patch
def __ft__(self: User): return Div('👤', self.name)

@patch
def __ft__(self: ChannelForMember):
    return A(id=f"channel-{self.channel_id}-{self.member_id}", hx_target="#main", hx_get=f"/c/{self.channel_id}", hx_push_url="true", hx_swap_oob="true")(
        Div(f'📢 {self.channel_name}') if not self.has_unread_messages else Strong(f'📢 {self.channel_name}')
    )

@patch
def __ft__(self: ChannelMessage): return Div('👤', Strong(self.name))

@patch
def __ft__(self: ChannelMessageWCtx):
    return Div(cls='flex items-start mb-4 text-sm')(
        Img(src=self.u_image_url, cls='w-10 h-10 rounded mr-3'),
        Div(cls='flex-1 overflow-hidden')(
            Div(
                Span(f"{self.u_name}", cls='font-bold'),
                Span(self.created_at, cls='text-grey text-xs')
            ),
            P(self.message, cls='text-black leading-normal')
        )
    )

@patch
def __ft__(self: ChannelPlaceholder):
    pass    

## end of UI

def Layout(content: FT, m: Member, w: Workspace) -> FT:
    print(f"MEMBER: {m} WORKSPACE: {w}")
    return Body(data_uid=m.user_id,data_wid=1,data_mid=m.id, cls="font-sans antialiased h-screen flex bg-background", hx_ext='ws', ws_connect=f'/ws?mid={m.id}')(
        Div(cls="bg-background flex-none w-64 pb-6 hidden md:block")(
            w,
            Separator(),
            *map(lambda ch: ChannelForMember.from_channel_member(ch), channel_members(where=f"member={m.id}")),
            Separator(),
            *users(where=f"id in (select user_id from member where workspace_id={w.id}) and id != {m.user_id}")
        ),
        Div(id="main", cls="flex-1 flex flex-col bg-white overflow-hidden")(content),
        HtmxOn('wsConfigSend', """
            console.log(">>>>>>>>>>>>>>>>>>>>>>", event);
            if (event.detail.parameters.command !== "ping") { throw new Error(`Invalid command: ${event.detail.parameters.command}`) }
            
            event.detail.parameters = {
               command: event.detail.parameters.command,
               d: { cid: event.detail.parameters.cid },
               auth: { mid: document.querySelector("body").getAttribute("data-mid") }
            };
        """
        )
    )

@dataclass
class Login: name:str; email:str


@rt("/login")
def get():
    frm = Form(action='/login', method='post')(
        Input(id='name', placeholder='Name'),
        Input(id='email', type='email', placeholder='Email'),
        Button('login'),
    )
    return Titled("Login", frm)

@rt("/login")
def post(login:Login, sess):
    if not login.name or not login.email: return login_redir
    if len(users(where=f"email='{login.email}'")) != 0: raise HTTPException(400, "User with this email already exists")

    user, workspace = users.insert(User(name=login.name, email=login.email, image_url=get_image_url(login.email))), workspaces()[0]
    # automatically associate the user with the first workspace + channel
    member = members.insert(Member(user_id=user.id, workspace_id=workspace.id))
    for channel in channels():
        cm = channel_members.insert(ChannelMember(channel=channel.id, member=member.id))
        # mark all messages as read
    sess['mid'], sess['wid'] = member.id, workspace.id
    return RedirectResponse('/', status_code=303)


@rt('/')
def home(): return Redirect(f"/c/{channels()[0].id}")

@rt("/healthcheck")
def get(): return JSONResponse({"status": "ok"})

async def dispatch_incoming_message(m: ChannelMessage):
    print(f"dispatching message: {m}")
    print(f'initial channel members: {channel_members(where=f"channel={m.channel}")}')
    members_to_notify = list(filter(lambda cm: cm.member != m.sender, channel_members(where=f"channel={m.channel}")))
    print(f">>>>>> members are: {members_to_notify}")
    print(f">>>>>>> message is: {m}")
    m_with_ctx = ChannelMessage.with_ctx(m)
    for member in members_to_notify:
        s = sockets(where=f"mid={member.member}")
        logger.debug(f"sockets {s}")
        # send message to each socket
        for c_s in s:
            logger.debug(f"sending message to {c_s.sid} {connections[c_s.sid]}")
            await connections[c_s.sid](Div(id=f"msg-list-{m.channel}", hx_swap_oob="beforeend")(m_with_ctx))
            await connections[c_s.sid](ChannelForMember.from_channel_member(member))

@rt('/messages/send', methods=['POST'])
def send_msg(msg:str, cid:int, req: Request):
    m = req.scope['m']
    cm = channel_messages.insert(ChannelMessage(channel=cid, sender=m.id, message=msg))
    new_message = ChannelMessage.with_ctx(cm)
    return new_message, BackgroundTask(dispatch_incoming_message, m=cm)

@rt('/c/messages/{cid}')
def channel_message(req: Request, cid: int):
    # get offset from query params
    offset = int(req.query_params.get("offset", 0))
    msgs, new_offset = ChannelMessageWCtx.latest(cid, offset)
    logger.debug(f"MESSAGES: {len(msgs)}")
    
    s = f"""el.scrollTop = el.scrollHeight;""" if offset == 0 else ""
    
    return Div(x_init=f"""
        function(offset){{
            const el = document.getElementById("msg-list-{cid}");
            console.log(">>>>>>>>> messages are in, yo.", offset, el);
            el.setAttribute("hx-get", "/c/messages/{cid}?offset=" + offset);
            htmx.process(el);
        }}({new_offset})  
    """), *msgs
    # ⬆️ only include scroller if it looks like we have more messages to load 


@rt('/c/{cid}')
def channel(req: Request, cid: int):
    m, w, frm_id, msgs_id = req.scope['m'], req.scope['w'], f"f-{cid}", f"msg-list-{cid}"
    channel = channels[cid]
    channel_for_member = ChannelForMember.from_channel_member(channel_members(where=f"channel={cid} and member={m.id}")[0]).mark_all_as_read()
    convo = Div(cls='border-b flex px-6 py-2 items-center flex-none', hx_trigger="every 5s", hx_vals=f'{{"command": "ping", "cid": {cid} }}', **{"ws_send": "true"})(
        Div(cls='flex flex-col')(
            H3(cls='text-grey-darkest mb-1 font-extrabold')(f"#{channel.name}"),
            Div("Chit-chattin' about ugly HTML and mixing of concerns.", cls='text-grey-dark text-sm truncate')
        ),
    ), Div(id=msgs_id, hx_swap="afterbegin", hx_trigger="scroll[checkChatWindowScroll()] delay:500ms", cls='scroller px-6 py-4 flex-1 overflow-y-scroll')(
        Div(hx_trigger="load", hx_get=f"/c/messages/{cid}", hx_swap="outerHTML", style="height: 4000px;", x_init=f"""
            function(){{
                const offset = 240;
                const el = document.getElementById("msg-list-{cid}");
                el.scrollTop = el.scrollHeight;
                window.checkChatWindowScroll = function() {{
                    console.log(">>>>>>>>>>> checking scroll position", el.scrollTop);
                    return el.scrollTop <= offset;
                }}
            }}()
           """
        )
    ), Div(cls='pb-6 px-4 flex-none')(
        Div(cls='flex rounded-lg border-2 border-grey overflow-hidden')(
            Span(cls='text-3xl text-grey border-r-2 border-grey p-2')(
                NotStr("""<svg class="fill-current h-6 w-6 block" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M16 10c0 .553-.048 1-.601 1H11v4.399c0 .552-.447.601-1 .601-.553 0-1-.049-1-.601V11H4.601C4.049 11 4 10.553 4 10c0-.553.049-1 .601-1H9V4.601C9 4.048 9.447 4 10 4c.553 0 1 .048 1 .601V9h4.399c.553 0 .601.447.601 1z"></path></svg>""")
            ),
            Form(id=frm_id, hx_post="/messages/send", hx_target=f"#{msgs_id}", hx_swap="beforeend",
                 **{ "hx-on::after-request": f"""document.querySelector("#{frm_id}").reset();"""}
            )(
                Input(id='msg'),
                Input(name='cid', type="hidden", value=cid)
            ),
            # TODO: figure out scrolling situation
            # previous implementation: document.getElementById("{msgs_id}").scrollTop = document.getElementById("{msgs_id}").scrollHeight;
        )
    )
    return [convo, channel_for_member] if req.headers.get('Hx-Request') else Layout(convo, m, w)

def on_conn(ws, send):
    try:
        m, sid = members[int(ws.query_params.get("mid"))], str(id(ws))
        connections[sid] = send
        for s in sockets(where=f"mid={m.id}"): sockets.delete(s.sid)
        sockets.insert(Socket(sid=sid, mid=m.id))
    except NotFoundError: raise WebSocketException(400, "Missing member id")
    
def on_disconn(ws):
    sid = str(id(ws))
    sockets.delete(sid)
    connections.pop(sid, None)

async def process_ping(cmd: PingCommand, member: Member):
    print(f">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> got ping {cmd}")
    # mark all messages as read in cid channel
    channel_for_member = ChannelForMember.from_channel_member(channel_members(where=f"channel={cmd.cid} and member={member.id}")[0]).mark_all_as_read()
    await ws_send_to_member(member.id, channel_for_member)

@app.ws('/ws', conn=on_conn, disconn=on_disconn)
async def ws(command:str, auth:dict, d: dict, ws):
    print(f">>>>>>>>>>>>>> got message in socket {command}")
    print(f">>>>>>>>>>>>>> got message in socket {auth}")
    print(f">>>>>>>>>>>>>> got message in socket {d}")

    mid = int(auth['mid'])
    logger.debug(f"socket ID is {str(id(ws))}")
    socket = sockets[str(id(ws))]
    logger.debug(f"got socket {socket}")
    logger.debug(f"got command {command} with payload {json.dumps(d)}")
    
    cmd = Command.from_json(command, json.dumps(d))
    await { "ping": process_ping }[cmd.cmd](cmd, members[mid])

serve()

## ================================ Tests

@pytest.fixture(scope="session", autouse=True)
def create_test_database():
    setup_database(test=True)
    # yield
    # db.conn.close()

@pytest.fixture()
def client():
    yield Client(app)

def test_commands():
    cmd = Command.from_json("ping", '{"cid": 1}')
    assert isinstance(cmd, PingCommand)
    assert cmd.cid == 1

def test_healthcheck(client):
    response = client.get('/healthcheck')
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_auth(client):
    assert len(users()) == 0
    assert len(workspaces()) == 1
    assert len(channels()) == 2
    assert len(members()) == 0
    assert len(channel_members()) == 0

    response: Response = client.get('/')

    assert response.status_code == 303
    assert response.headers['location'] == '/login'

    response = client.post('/login', data={"name": "Philip", "email": "philip@thebakery.io"})
    
    assert len(users()) == 1
    assert len(members()) == 1
    assert len(channel_members()) == 2

    assert response.status_code == 303
    assert response.headers['location'] == '/'

def test_channel_data_helpers():
    u1, u2, workspace, channel = users.insert(User(name="Philip", email="p@g.com")), users.insert(User(name="John", email="j@g.com")), workspaces()[0], channels()[0]
    m1, m2 = members.insert(Member(user_id=u1.id, workspace_id=workspace.id)), members.insert(Member(user_id=u2.id, workspace_id=workspace.id))
    cm1, cm2 = channel_members.insert(ChannelMember(channel=channel.id, member=m1.id)), channel_members.insert(ChannelMember(channel=channel.id, member=m2.id))

    # no messages in the channel
    assert channel.last_message_ts is None 

    # user 1 sends message to the channel
    msg = channel_messages.insert(ChannelMessage(channel=channel.id, sender=m1.id, message="hello"))
    assert channel.last_message_ts == msg.created_at

    c4m1, c4m2 = ChannelForMember.from_channel_member(cm1), ChannelForMember.from_channel_member(cm2)

    assert c4m1.has_unread_messages is False
    assert c4m2.has_unread_messages is True

    # sleep a bit (so timestamps work correctly)
    time.sleep(0.1)

    # user 2 sends a message to the channel, seen indicator should be updated
    channel_messages.insert(ChannelMessage(channel=channel.id, sender=m2.id, message="hey"))

    c4m1, c4m2 = ChannelForMember.from_channel_member(cm1), ChannelForMember.from_channel_member(cm2)

    assert c4m1.has_unread_messages is True
    assert c4m2.has_unread_messages is False

    # can mark all as read
    c4m1 = c4m1.mark_all_as_read()

    assert c4m1.has_unread_messages is False
