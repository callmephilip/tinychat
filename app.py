import logging, json, time, dataclasses, typing, hashlib, urllib, pytest
from fasthtml.common import *
from shad4fast import *
from tractor import connect_tractor

# re https://www.creative-tim.com/twcomponents/component/slack-clone-1

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

bware = Beforeware(check_auth, skip=[r'/favicon\.ico', r'/static/.*', r'.*\.css', '/login', '/healthcheck', '/ws'])

app = FastHTMLWithLiveReload(ws_hdr=True, debug=True, hdrs=[
    ShadHead(tw_cdn=True),
    Script(src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js", defer=True),
], before=bware)
rt = app.route

logging.basicConfig(format="%(asctime)s - %(message)s",datefmt="🧵 %d-%b-%y %H:%M:%S",level=logging.DEBUG,handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

def get_image_url(email: str, s=250, d="https://www.example.com/default.jpg") -> str:
    email_hash, query_params = hashlib.sha256(email.lower().encode('utf-8')).hexdigest(), urllib.parse.urlencode({'d': d, 's': str(s)})
    return f"https://www.gravatar.com/avatar/{email_hash}?{query_params}"

# socket connections socket_id -> send
connections: Dict[str, typing.Awaitable] = {}

@dataclass(kw_only=True)
class TsRec: created_at: int = dataclasses.field(default_factory=lambda: int(time.time()))

@dataclass(kw_only=True)
class User(TsRec): id: int; name: str; email: str; image_url: str; is_account_enabled: bool = True
@dataclass(kw_only=True)
class Workspace(TsRec): id: int; name: str
@dataclass(kw_only=True)
class Channel(TsRec): id: int; name: str; workspace_id: int
@dataclass(kw_only=True)
class Member(TsRec): id: int; user_id: int; workspace_id: int
@dataclass(kw_only=True)
class ChannelMember(TsRec): id: int; channel: int; member: int
@dataclass(kw_only=True)
class ChannelMessage(TsRec): id: int; channel: int; sender: int; message: str

@dataclass
class ChanneMessageWCtx:
    id: int; created_at: int; message: str; u_name: str; u_image_url: str; c_id: int; c_name: str

    @staticmethod
    def latest(cid: int) -> List['ChanneMessageWCtx']:
        return list(map(lambda args: ChanneMessageWCtx(*args), db.execute("""
            SELECT id, created_at, message, u_name, u_image_url, c_id, c_name
            FROM messages_w_ctx ORDER BY created_at DESC LIMIT 100
        """)))[::-1]
    
    @staticmethod
    def by_id(message_id: int) -> 'ChanneMessageWCtx':
        return ChanneMessageWCtx(*next(db.execute(f"""
            SELECT id, created_at, message, u_name, u_image_url, c_id, c_name
            FROM messages_w_ctx WHERE id={message_id}
        """)))

@dataclass(kw_only=True)
class PrivateMessage(TsRec): id: int; sender: int; receiver: int; message: str
@dataclass(kw_only=True)
class Socket(TsRec): sid: str; mid: int

@dataclass
class Command:
    cmd: str

    @staticmethod
    def from_json(cmd: str, data: str) -> 'Command':
        if cmd == "send_msg": return SendMsgCommand(cmd=cmd, **json.loads(data))
        raise ValueError(f"Invalid command: {cmd}")

@dataclass
class SendMsgCommand(Command): cid: int; msg: str

def setup_database(test=False):
    global db
    global users, workspaces, channels, members, channel_members, channel_messages, private_messages, sockets

    db = database('./data/data.db') if not test else database(':memory:')

    users = db.create(User, pk="id")
    workspaces = db.create(Workspace, pk="id")
    # TODO: figure out why foreign key are not enforced 
    channels = db.create(Channel, pk="id", foreign_keys=[("workspace_id", "workspace", "id")])
    # TODO: figure out why foreign key are not enforced 
    members = db.create(Member, pk="id", foreign_keys=[("user_id", "user", "id"), ("workspace_id", "workspace", "id")])
    channel_members = db.create(ChannelMember, pk="id", foreign_keys=[("channel", "channel", "id"), ("member", "member", "id")])
    channel_messages = db.create(ChannelMessage, pk="id", foreign_keys=[("channel", "channel", "id"), ("sender", "user", "id")])  
    private_messages = db.create(PrivateMessage, pk="id", foreign_keys=[("sender", "member", "id"), ("receiver", "member", "id")])
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
    if channels.count == 0: channels.insert(Channel(name="general", workspace_id=1))

    if not test: connect_tractor(app, db.conn)

setup_database()

## UI

@patch
def __ft__(self: Workspace): return Div('👨‍🏭', Strong(self.name))

@patch
def __ft__(self: User): return Div('👤', Strong(self.name))

@patch
def __ft__(self: Channel): return A(hx_target="#main", hx_get=f"/c/{self.id}")(Div('📢', Strong(self.name)))

@patch
def __ft__(self: ChannelMessage): return Div('👤', Strong(self.name))

@patch
def __ft__(self: ChanneMessageWCtx):
    return Div(cls='flex items-start mb-4 text-sm')(
        Img(src=self.u_image_url, cls='w-10 h-10 rounded mr-3'),
        Div(cls='flex-1 overflow-hidden')(
            Div(
                Span(self.u_name, cls='font-bold'),
                Span(self.created_at, cls='text-grey text-xs')
            ),
            P(self.message, cls='text-black leading-normal')
        )
    )

## end of UI

def Layout(content: FT, m: Member, w: Workspace) -> FT:
    print(f"MEMBER: {m} WORKSPACE: {w}")
    return Body(data_uid=m.user_id,data_wid=1,data_mid=m.id, cls="font-sans antialiased h-screen flex bg-background", hx_ext='ws', ws_connect=f'/ws?mid={m.id}')(
        Div(cls="bg-background flex-none w-64 pb-6 hidden md:block")(
            w,
            Separator(),
            *users(where=f"id in (select user_id from member where workspace_id={w.id})"),
            Separator(),
            *channels(where=f"workspace_id={w.id}")
        ),
        Div(id="main", cls="flex-1 flex flex-col bg-white overflow-hidden")(content),
        HtmxOn('wsConfigSend', """
            console.log(">>>>>>>>>>>>>>>>>>>>>>", event);
            if (event.detail.parameters.command !== "send_msg") { throw new Error(`Invalid command: ${event.detail.parameters.command}`) }
            
            event.detail.parameters = {
               command: event.detail.parameters.command,
               d: {
                   cid: event.detail.parameters.cid,
                   msg: event.detail.parameters.msg
               },
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
    channel_members.insert(ChannelMember(channel=channels()[0].id, member=member.id))
    sess['mid'], sess['wid'] = member.id, workspace.id
    return RedirectResponse('/', status_code=303)


@rt('/')
def home(): return Redirect(f"/c/{channels()[0].id}")

@rt("/healthcheck")
def get(): return JSONResponse({"status": "ok"})

@rt('/c/{cid}')
def channel(req: Request, cid: int):
    m, w = req.scope['m'], req.scope['w']
    convo = Div(cls='border-b flex px-6 py-2 items-center flex-none')(
        Div(cls='flex flex-col')(
            H3(cls='text-grey-darkest mb-1 font-extrabold')(f"Channel {cid}"),
            Div("Chit-chattin' about ugly HTML and mixing of concerns.", cls='text-grey-dark text-sm truncate')
        ),
    ), Div(id=f"msg-list-{cid}", cls='scroller px-6 py-4 flex-1 overflow-y-scroll')(
        Div(x_init=f"""
            function(){{
                var msgList{cid} = document.getElementById("msg-list-{cid}"); msgList{cid}.scrollTop = msgList{cid}.scrollHeight;
                setTimeout(function() {{
                    var div = document.createElement('div');
                    div.setAttribute("hx-get", "/c/{cid}/previous");
                    div.setAttribute("hx-trigger", "intersect once");
                    document.getElementById('msg-list-{cid}').insertBefore(div, document.getElementById('msg-list-{cid}').firstChild);
                    htmx.process(div);
                }}, 500)
            }}()  
        """),
        *ChanneMessageWCtx.latest(cid),
    ), Div(cls='pb-6 px-4 flex-none')(
        Div(cls='flex rounded-lg border-2 border-grey overflow-hidden')(
            Span(cls='text-3xl text-grey border-r-2 border-grey p-2')(
                NotStr("""<svg class="fill-current h-6 w-6 block" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M16 10c0 .553-.048 1-.601 1H11v4.399c0 .552-.447.601-1 .601-.553 0-1-.049-1-.601V11H4.601C4.049 11 4 10.553 4 10c0-.553.049-1 .601-1H9V4.601C9 4.048 9.447 4 10 4c.553 0 1 .048 1 .601V9h4.399c.553 0 .601.447.601 1z"></path></svg>""")
            ),
            Form(Input(id='msg'), Input(name='command', type="hidden", value="send_msg", cls='w-full px-4'), Input(name='cid', type="hidden", value="1"), id='form', ws_send=True)
        )
    )
    return convo if req.headers.get('Hx-Request') else Layout(convo, m, w)

def on_conn(ws, send):
    # TODO: figure out socket authentication
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

@app.ws('/ws', conn=on_conn, disconn=on_disconn)
async def ws(command:str, auth:dict, d: dict, ws):
    mid = int(auth['mid'])
    logger.debug(f"socket ID is {str(id(ws))}")
    socket = sockets[str(id(ws))]
    logger.debug(f"got socket {socket}")
    logger.debug(f"got command {command} with payload {json.dumps(d)}")

    cmd = Command.from_json(command, json.dumps(d))

    async def on_send_msg(cmd: SendMsgCommand):
        # get all members of the channel
        c_ms = channel_members(where=f"channel={cmd.cid}")
        logger.debug(f"channel members {c_ms}")
        new_msg = channel_messages.insert(ChannelMessage(channel=cmd.cid, sender=mid, message=cmd.msg))
        logger.debug(f"MESSAGES_W_CTX: {ChanneMessageWCtx.latest(cmd.cid)}")

        for m in c_ms:
            s = sockets(where=f"mid={m.member}")
            logger.debug(f"sockets {s}")
            # send message to each socket
            for s in s:
                logger.debug(f"sending message to {s.sid} {connections[s.sid]}")
                await connections[s.sid](
                    Div(id=f"msg-list-{cmd.cid}", hx_swap_oob="beforeend")(
                        Div(x_init="console.log('>>>>>>>>>initialized!')"),
                        ChanneMessageWCtx.by_id(new_msg.id)
                    )
                )

    await {
        "send_msg": on_send_msg
    }[cmd.cmd](cmd)

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
    cmd = Command.from_json("send_msg", '{"cid": 1, "msg": "hello"}')
    assert isinstance(cmd, SendMsgCommand)
    assert cmd.cid == 1
    assert cmd.msg == "hello"

def test_healthcheck(client):
    response = client.get('/healthcheck')
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_auth(client):
    assert len(users()) == 0
    assert len(workspaces()) == 1
    assert len(channels()) == 1
    assert len(members()) == 0
    assert len(channel_members()) == 0

    response: Response = client.get('/')

    assert response.status_code == 303
    assert response.headers['location'] == '/login'

    response = client.post('/login', data={"name": "Philip", "email": "philip@thebakery.io"})
    
    assert len(users()) == 1
    assert len(members()) == 1
    assert len(channel_members()) == 1

    assert response.status_code == 303
    assert response.headers['location'] == '/'
