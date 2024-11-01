import logging, json, time, dataclasses, typing, hashlib, urllib, base64, random, threading, uvicorn, contextlib, user_agents
import urllib.parse
from lorem_text import lorem
from fasthtml.common import *
from fasthtml.core import htmxsrc, fhjsscr, charset
from fasthtml.svg import Svg
from shad4fast import *
from shad4fast.components.button import btn_variants, btn_base_cls, btn_sizes
from lucide_fasthtml import Lucide
from tractor import connect_tractor

try:
    import pytest
    from playwright.sync_api import Page, Playwright, expect
except ImportError: pass

# TODO: fix tests
# TODO: get server stats
# TODO: figure out if there is a way to simplify some of the queries using triggers and views instead
# TODO: figure out socket authentication
# TODO: support markdown in messages?
# TODO: maybe a login that is more like a login? (email link or is this too much)
# TODO: user roles + admin mode (when you are the first guy in)


# The beginning of wisdom is the ability to call things by their right names - Confucius

# +-------------------------------+-------------------------------+
# | Channels                       | # general                     |
# +-------------------------------+-------------------------------+
# | # general                      | [John] Hey team, how's it going?|
# | # project-updates              | [Alice] Almost done!          |
# | # random                       | [Mike] I need help with the   |
# | # dev-team                     |        deployment script.     |
# |                                 | [Alice] Sure! I'll DM you.    |
# |                                 |                               |
# |                                 |                               |
# |                                 |                               |
# |                                 |                               |
# |                                 |                               |
# |                                 |                               |
# +-------------------------------+-------------------------------+
# | Users                          | > Type your message here...   |
# +-------------------------------+-------------------------------+
# | @John                          |                               |
# | @Alice                         |                               |
# | @Mike                          |                               |
# | @Sarah                         |                               |
# +-------------------------------+-------------------------------+

def build_icon(content: str): return lambda cls: Svg(width="24", height="24", viewBox="0 0 24 24", fill="none", stroke="currentColor", stroke_width="2", stroke_linecap="round", stroke_linejoin="round", cls=cls)(NotStr(content))
I_USER = build_icon("<path d=\"M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2\"></path><circle cx=\"12\" cy=\"7\" r=\"4\"></circle>") 
I_USERS = build_icon("<path d=\"M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2\"></path><circle cx=\"9\" cy=\"7\" r=\"4\"></circle><path d=\"M22 21v-2a4 4 0 0 0-3-3.87\"></path><path d=\"M16 3.13a4 4 0 0 1 0 7.75\"></path>")
I_PLUS = NotStr("""<svg class="fill-current h-6 w-6 block" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M16 10c0 .553-.048 1-.601 1H11v4.399c0 .552-.447.601-1 .601-.553 0-1-.049-1-.601V11H4.601C4.049 11 4 10.553 4 10c0-.553.049-1 .601-1H9V4.601C9 4.048 9.447 4 10 4c.553 0 1 .048 1 .601V9h4.399c.553 0 .601.447.601 1z"></path></svg>""")
I_ARROW_LEFT = build_icon("<path d=\"m12 19-7-7 7-7\"></path><path d=\"M19 12H5\"></path>")
I_GH = build_icon("<path d=\"M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4\"></path><path d=\"M9 18c-4.51 2-5-2-7-2\"></path>")
I_PLAY = build_icon("<polygon points=\"6 3 20 12 6 21 6 3\"></polygon>")

# re https://www.creative-tim.com/twcomponents/component/slack-clone-1
# re https://systemdesign.one/slack-architecture/

login_redir = RedirectResponse('/login', status_code=303)
def check_auth(req, sess):
    mid, wid = sess.get('mid', None), sess.get('wid', None)
    # If the session key is not there, it redirects to the login page.
    if not mid or not wid: return login_redir

    try: req.scope['m'], req.scope['w'] = members[int(mid)], workspaces[int(wid)]
    except NotFoundError: return login_redir

    # `xtra` is part of the MiniDataAPI spec. It adds a filter to queries and DDL statements,
    # to ensure that the user can only see/edit their own todos.
    # todos.xtra(name=auth)

def get_ts() -> int: return int(time.time() * 1000)
def clsx(*args): return " ".join([arg for arg in args if arg])

bware = Beforeware(check_auth, skip=[r'/favicon\.ico', r'/static/.*', r'.*\.css', '/', '/login', '/healthcheck'])

App = FastHTMLWithLiveReload if os.environ.get("LIVE_RELOAD", False) else FastHTML
app = App(debug=True, default_hdrs=False, hdrs=[
    htmxsrc, fhjsscr, charset,
    Meta(name="viewport", content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"),
    ShadHead(tw_cdn=True),
    Script(src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js", defer=True),
    Style("""  
        .messages-loading.htmx-request {
          padding: 10px;
          background-image: url('https://htmx.org/img/bars.svg');
          background-repeat: no-repeat;
          background-position: center;
        }
    """),
], exts="ws", before=bware)
rt = app.route

logging.basicConfig(format="%(asctime)s - %(message)s",datefmt="🧵 %d-%b-%y %H:%M:%S",level=logging.DEBUG,handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

def get_image_url(name: str) -> str: return f"https://ui-avatars.com/api/?name={urllib.parse.quote(name)}&background=random&size=256"

# socket connections socket_id -> send
connections: Dict[str, typing.Awaitable] = {}

@dataclass
class Settings:
    workspace_name: str = "tinychat"
    host_url: str = "http://localhost:5001"
    default_channels: List[str] = dataclasses.field(default_factory=lambda: ["general", "random"])
    message_history_page_size = 40
    ping_interval_in_seconds: float = 5


settings = Settings()

@dataclass(kw_only=True)
class TsRec: created_at: int = dataclasses.field(default_factory=get_ts)

@dataclass(kw_only=True)
class User(TsRec): id: int; name: str; image_url: str; is_account_enabled: bool = True

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
    channel_name: str; channel: Channel; channel_member: 'ChannelMember'; has_unread_messages: bool; is_selected: bool = False

    @staticmethod
    def from_channel_member(channel_member: 'ChannelMember') -> 'ChannelForMember':
        c: Channel = channels[channel_member.channel]
        last_message_ts = c.last_message_ts

        if last_message_ts is None: has_unread_messages = False
        else:
            seen = channel_message_seen_indicators(where=f"channel_id={c.id} AND member_id={channel_member.member}")
            seen = seen[0] if len(seen) > 0 else None
            if not seen or not seen.last_seen_ts: has_unread_messages = True
            else: has_unread_messages = c.last_message_ts > seen.last_seen_ts

        other_member = channel_members(where=f"channel={c.id} and member!={channel_member.member}")[0] if c.is_direct else None
        name = c.name if not c.is_direct else other_member.name

        return ChannelForMember(channel_name=name, channel=c, channel_member=channel_member, has_unread_messages=has_unread_messages)
    
    def mark_all_as_read(self) -> 'ChannelForMember':
        member_id = self.channel_member.member
        seen = channel_message_seen_indicators(where=f"channel_id={self.channel.id} AND member_id={member_id}")
        seen = seen[0] if len(seen) > 0 else None
        if seen:
            seen.last_seen_ts = self.channel.last_message_ts
            channel_message_seen_indicators.update(seen)
        else:
            channel_message_seen_indicators.insert(ChannelMessageSeenIndicator(channel_id=self.channel.id, member_id=member_id, last_seen_ts=self.channel.last_message_ts))
        return ChannelForMember.from_channel_member(channel_members(where=f"channel={self.channel.id} and member={member_id}")[0])

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
class ChannelMember(TsRec):
    channel: int; member: int

    @property
    def name(self) -> str: return members[self.member].name

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
    def encode_cursor(ts: int, direction: typing.Literal["prev", "next"]) -> str: return str(base64.b64encode(f"{ts}-{direction}".encode("ascii")), encoding="ascii") 

    @staticmethod
    def decode_cursor(cursor: str) -> Tuple[int, str]:
        if not cursor: return 0, None
        r = tuple(map(lambda x: x.decode("ascii"), base64.b64decode(cursor).split(b"-")))
        return int(r[0]), r[1]

    @staticmethod
    def fetch(cid: int, cursor: Optional[str] = None) -> Tuple[List['ChannelMessageWCtx'], Optional[str], Optional[str]]:
        # returns list of messages, previous and next cursors

        prev_cursor, next_cursor = None, None
        ts, direction = ChannelMessageWCtx.decode_cursor(cursor) if cursor else (0, None)

        q = f"""SELECT id, created_at, message, u_name, u_image_url, c_id, c_name FROM messages_w_ctx WHERE c_id={cid}"""

        if not cursor: q = f"""{q} ORDER BY created_at DESC LIMIT {settings.message_history_page_size}"""
        elif direction == "prev": q = f"""{q} AND created_at < {ts} ORDER BY created_at DESC LIMIT {settings.message_history_page_size}"""
        else: q = f"""{q} AND created_at > {ts} ORDER BY created_at ASC LIMIT {settings.message_history_page_size}"""
        
        rs = list(map(lambda args: ChannelMessageWCtx(*args), db.execute(q)))
    
        if len(rs) == 0: return [], prev_cursor, next_cursor

        if cursor:
            if direction == "prev":
                # if we are going back, then previous cursor exists if we have enough messages
                prev_cursor = ChannelMessageWCtx.encode_cursor(rs[-1].created_at, "prev") if len(rs) == settings.message_history_page_size else None
                # next cursor should exist
                next_cursor = ChannelMessageWCtx.encode_cursor(rs[0].created_at, "next")
            else:
                # if we are going forward, then next cursor exists if we have enough messages
                next_cursor = ChannelMessageWCtx.encode_cursor(rs[0].created_at, "next") if len(rs) == settings.message_history_page_size else None
                # previous cursor should exist
                prev_cursor = ChannelMessageWCtx.encode_cursor(rs[-1].created_at, "prev")
        else:
            # when no cursor is provided, we can only move backwards, assuming there are enough messages
            prev_cursor = ChannelMessageWCtx.encode_cursor(rs[-1].created_at, "prev") if len(rs) == settings.message_history_page_size else None 

        return rs, prev_cursor, next_cursor

    
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
class ChannelPlaceholder: member: Member

@dataclass
class ListOfChannelsForMember:
    # TODO: cache properties?
    member: Member; current_channel: Channel

    @property
    def has_unread_messages(self) -> bool:
        return any(map(lambda ch: ch.has_unread_messages, self.group_channels + self.direct_channels))

    @property
    def group_channels(self) -> List[ChannelForMember]:
        r = list(map(lambda ch: ChannelForMember.from_channel_member(ch), channel_members(where=f"member={self.member.id} and channel in (select id from channel where is_direct=0)")))
        for c in r: c.is_selected = c.channel.id == self.current_channel.id
        return r

    @property
    def direct_channels(self) -> List[ChannelForMember]:
        # TODO: figure out a cleaner way to do this
        # it's tricky with direct channels, because we want this to check "unread" message status for current member (self.member)
        # but refer to the channel by the other member name
        dcs = list(map(lambda c: c.id, channels(where=f"is_direct=1 and id in (select channel from channel_member where member={self.member.id})")))
        dcs = ",".join(map(str, dcs))
        r = list(map(lambda ch: ChannelForMember.from_channel_member(ch), channel_members(where=f"""member == {self.member.id} and channel in ({dcs})""")))
        for c in r: c.is_selected = c.channel.id == self.current_channel.id
        return r

    @property
    def direct_channel_placeholders(self) -> List[ChannelPlaceholder]:
        return list(map(lambda m: ChannelPlaceholder(member=m), members(where=f"""
            id not in (
                select member from channel_member where channel in (
                    select id from channel where workspace_id = {self.member.workspace_id} and is_direct=1 and id in (
                        select channel from channel_member where member={self.member.id}
                    )
                )
            ) and id != {self.member.id}
        """)))

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
    
    # setup triggers 
    db.conn.execute(f"""CREATE TRIGGER IF NOT EXISTS update_last_seen_message_ts AFTER INSERT ON channel_message
        BEGIN
            INSERT INTO channel_message_seen_indicator(channel_id, member_id, last_seen_ts) VALUES(new.channel, new.sender, new.created_at)
                ON CONFLICT(channel_id, member_id) DO UPDATE SET last_seen_ts=new.created_at;
        END""")

    if workspaces.count == 0: workspaces.insert(Workspace(name=settings.workspace_name))
    if channels.count == 0: [channels.insert(Channel(name=name, workspace_id=1)) for name in settings.default_channels]

    # add test data if in test mode
    if test:
        u = users.insert(User(name="Phil"))
        member = members.insert(Member(user_id=u.id, workspace_id=workspaces()[0].id))
        for channel in channels(): channel_members.insert(ChannelMember(channel=channel.id, member=member.id))
        ts, target_channel = get_ts(), channels()[0]
        for i in range(1200): channel_messages.insert(ChannelMessage(created_at=ts + i, channel=target_channel.id, sender=member.id, message=f"{i+1} {lorem.sentence()}"))

    # if not test: connect_tractor(app, db.conn)
    

setup_database(os.environ.get("TEST_MODE", False))

async def ws_send_to_member(member_id: int, data):
    s = sockets(where=f"mid={member_id}")[0]
    logger.debug(f"sockets {s}")
    # send message to each socket
    logger.debug(f"sending message to {s.sid} {connections[s.sid]}")
    await connections[s.sid](data)

## UI

@patch
def __ft__(self: Workspace): return H1(cls="text-l font-bold")(f'👨‍🏭 {self.name}')

@patch
def __ft__(self: User): return Div('👤', self.name)

@patch
def __ft__(self: ChannelForMember):
    cls=clsx("w-full justify-start", btn_base_cls, btn_sizes["sm"], not self.is_selected and btn_variants["ghost"], self.is_selected and btn_variants["default"], self.has_unread_messages and "has-unread-messages")
    icon = I_USER(cls="mr-2 h-4 w-4") if self.channel.is_direct else I_USERS(cls="mr-2 h-4 w-4")
    return A(hx_target="#main", hx_get=f"/c/{self.channel.id}", hx_push_url="true", cls=cls, **{ "data-testid": f"nav-to-channel-{self.channel.id}" }, style="justify-content: flex-start !important;")(
        icon, Div(f'{self.channel_name}') if not self.has_unread_messages else Strong(self.channel_name)
    )

@patch
def __ft__(self: ChannelPlaceholder):
    cls=clsx("w-full justify-start", btn_sizes["sm"], btn_base_cls, btn_variants["ghost"])
    return A(hx_target="#main", hx_get=f"/direct/{self.member.id}", hx_push_url="true", **{ "data-testid": f"dm-{self.member.id}"}, cls=cls, style="justify-content: flex-start !important;")(
        I_USER(cls="mr-2 h-4 w-4"),
        self.member.name
    )

@patch
def __ft__(self: ChannelMessageWCtx):
    return Div(id=f"chat-message-{self.id}", cls='chat-message flex items-start mb-4 text-sm')(
        Img(src=self.u_image_url, cls='w-10 h-10 rounded mr-3'),
        Div(cls='flex-1 overflow-hidden')(
            Div(
                Span(f"{self.u_name}", cls='font-bold'),
                Span(cls='pl-2 text-grey text-xs', **{ "x-text": f"Intl.DateTimeFormat(navigator.language, {{ month: 'long', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false  }}).format(new Date({self.created_at}))" })
            ),
            P(self.message, cls='text-black leading-normal')
        )
    )

@patch
def __ft__(self: ListOfChannelsForMember):
    return Div(id="channels", hx_swap_oob="true")(
        Div(cls="px-3 py-2")(
            H2(cls="mb-2 px-4 text-lg font-semibold tracking-tight")("Groups"),
            Div(*self.group_channels, cls=" px-1")
        ),
        Div(cls="px-3 py-2")(
            H2(cls="mb-2 px-4 text-lg font-semibold tracking-tight")("DMs"),
            ScrollArea(*self.direct_channels, *self.direct_channel_placeholders, cls="h-[300px] px-1")
        )
    )

## end of UI

def Sidebar(m: Member, w: Workspace, channel: Channel, is_mobile: bool):
    attrs = { "data-testid": "sidebar", "hx-on::after-request": "setTimeout(() => { document.querySelector('#mobile-menu').click(); }, 300)"} if is_mobile else {}
    return Div(cls="flex-none md:w-64 block overflow-hidden", **attrs)(
        Div(cls="space-y-4")(
            # workspace info
            Div(cls="px-3 py-2 border-b")(w),
            ListOfChannelsForMember(member=m, current_channel=channel),
            # profile info
            Sheet(
                Div(cls="h-full")(
                    A(href=f"/logout", **{ "data-testid": "logout" }, cls=clsx(btn_sizes["sm"], btn_base_cls, btn_variants["default"]))("Logout")
                ),
                side="bottom",
                trigger=Button(cls='flex items-center px-4 mx-4 fixed bottom-6', variant="ghost", data_ref="sheet-trigger", **{ "data-testid": "profile-menu" })(
                    Img(src=m.image_url, cls='w-10 h-10 mr-3'),
                    Div(cls='text-sm')(
                        Div(m.name, cls='font-bold'),
                        Div('Online', cls='text-xs font-bold text-green-400')
                    )
                )
            )
        )   
    )

def LandingLayout(*content) -> FT:
    return Body(cls="font-sans antialiased h-dvh flex bg-background overflow-hidden")(
        Div(cls='container relative flex-col h-full items-center justify-center md:grid lg:max-w-none lg:grid-cols-1 lg:px-0')(
            Div(cls='absolute left-4 top-4 z-20 flex items-center text-lg font-medium')(A(href="/")("👨‍🏭 tinychat")),
            Div(cls='mx-auto my-24 flex w-full flex-col justify-center space-y-6 sm:w-[350px]')(content)
        )
    )

def Layout(*content, m: Member, w: Workspace, channel: Channel, is_mobile: bool) -> FT:
    return Body(cls="font-sans antialiased h-dvh flex bg-background overflow-hidden", hx_ext='ws', ws_connect=f'/ws?mid={m.id}')(
        # sidebar
        Sidebar(m, w, channel, is_mobile) if not is_mobile else None,
        # main content
        Div(id="main", cls="flex-1 flex flex-col bg-white overflow-hidden md:border-l")(content),
        # mobile version of the sidebar
        # based on the approach from https://dev.to/seppegadeyne/crafting-a-mobile-menu-with-tailwind-css-without-javascript-1814
        Label(fr='mobile-menu', cls='relative z-40 cursor-pointer')(
            Input(type='checkbox', id='mobile-menu', cls='peer hidden'),
            Div(cls='fixed inset-0 z-40 hidden h-full w-full bg-black/50 backdrop-blur-sm peer-checked:block'),
            Div(cls='fixed top-0 left-0 z-40 h-full w-full -translate-x-full overflow-y-auto overscroll-y-none transition duration-500 peer-checked:translate-x-0')(
                Div(cls='float-left min-h-full w-[85%] bg-white shadow-2xl')(
                    Sidebar(m, w, channel, is_mobile)
                )
            )
        ) if is_mobile else None,
        HtmxOn('oobAfterSwap', """
            if (event.detail.target.id.match(/channel-[0-9]+/ig)) {
               const height = Math.max(event.detail.target.clientHeight, event.detail.target.scrollHeight, event.detail.target.offsetHeight);
               if (Math.abs(event.detail.target.scrollTop) / height < 0.2) { event.detail.target.scrollTop = event.detail.target.scrollHeight; }
            }
        """),
    )

@rt("/")
def landing():
    return LandingLayout(
        Div(cls='flex flex-col space-y-2 text-center')(
            H1("Welcome to tinychat", cls='text-2xl font-semibold tracking-tight'),
            P("Chat so small it fits in 1 python file"),
            P("Try it, fork it, make it yours.", cls='text-sm text-muted-foreground')
        ),
        Div(cls="grid grid-cols-2 gap-6")(
            A(href="/login", cls=clsx(btn_base_cls, btn_variants["outline"], btn_sizes["default"]))(I_PLAY(cls="mr-2 h-4 w-4"),"Try it"),
            A(href="https://github.com/callmephilip/tinychat", cls=clsx(btn_base_cls, btn_variants["outline"], btn_sizes["default"]))(I_GH(cls="mr-2 h-4 w-4"),"Github")
        )
    )

@dataclass
class Login: name:str

@rt("/login")
def get(): return LandingLayout(Form(action='/login', method='post')(Div(cls="flex")(Input(id='name', placeholder='Name'), Button(cls="ml-4")('Log in'))))

@rt("/login")
def post(login:Login, sess):
    if not login.name: return login_redir

    user, workspace = users.insert(User(name=login.name, image_url=get_image_url(login.name))), workspaces()[0]
    # automatically associate the user with the first workspace + default group channels
    member = members.insert(Member(user_id=user.id, workspace_id=workspace.id))
    default_channels = ",".join(map(lambda c: f"'{c}'", settings.default_channels))
    for channel in channels(where=f"workspace_id={workspace.id} and name in ({default_channels})"): channel_members.insert(ChannelMember(channel=channel.id, member=member.id))
    sess['mid'], sess['wid'] = member.id, workspace.id

    return Redirect(f"/c/{channels()[0].id}")

@app.get("/logout")
def logout(sess):
    sess.pop("mid", None), sess.pop("wid", None)    
    return RedirectResponse("/", status_code=303)

@rt("/healthcheck")
def get(): return JSONResponse({"status": "ok"})

async def dispatch_incoming_message(m: ChannelMessage):
    members_to_notify = list(filter(lambda cm: cm.member != m.sender, channel_members(where=f"channel={m.channel}")))
    m_with_ctx = ChannelMessage.with_ctx(m)
    for member in members_to_notify:
        s = sockets(where=f"mid={member.member}")
        logger.debug(f"sockets {s}")
        # send message to each socket
        for c_s in s:
            logger.debug(f"sending message to {c_s.sid} {connections[c_s.sid]}")
            await connections[c_s.sid](Div(id=f"channel-{m.channel}", hx_swap="scroll:bottom", hx_swap_oob="afterbegin")(m_with_ctx))

@rt('/messages/send/{cid}', methods=['POST'])
def send_msg(msg:str, cid:int, req: Request):
    cm = channel_messages.insert(ChannelMessage(channel=cid, sender=req.scope['m'].id, message=msg))
    new_message = ChannelMessage.with_ctx(cm)
    return new_message, BackgroundTask(dispatch_incoming_message, m=cm)

@rt('/c/messages/{cid}')
def list_channel_messages(req: Request, cid: int):
    msgs, prev_cursor, _ = ChannelMessageWCtx.fetch(cid, req.query_params.get("c"))
    load_previous = Div(
        cls="messages-loading htmx-indicator", hx_get=f"/c/messages/{cid}?c={prev_cursor}", hx_indicator=".messages-loading",
        hx_trigger="intersect once", hx_target=f"#channel-{cid}", hx_swap=f"beforeend show:#chat-message-{msgs[-1].id}:top"
    ) if len(msgs) == settings.message_history_page_size else None
    # ⬆️ only include scroller if it looks like we have more messages to load
    return *msgs, load_previous

@rt('/c/{cid}')
def channel(req: Request, cid: int):
    is_mobile, m, w, frm_id, msgs_id, channel = user_agents.parse(req.headers.get('User-Agent')).is_mobile, req.scope['m'], req.scope['w'], f"f-{cid}", f"channel-{cid}", channels[cid]
    channel_name = f"#{channel.name}" if not channel.is_direct else channel_members(where=f"channel={cid} and member!={m.id}")[0].name
    ping_cmd = { "command": "ping", "d": { "cid": cid }, "auth": { "mid": m.id } }

    convo = [
        Div(cls="hidden", hx_trigger=f"load, every {settings.ping_interval_in_seconds}s", hx_vals=f'{json.dumps(ping_cmd)}', **{"ws_send": "true"}), 
        Div(cls='border-b flex md:px-6 py-2 items-center flex-none', style="position: fixed; width: 100%; background-color: white;" if is_mobile else "")(
            Div(cls='flex flex-row items-center')(
                Button(variant="ghost", **{ "data-testid":"show-mobile-sidebar", "onclick": "document.getElementById('mobile-menu').click()"})(I_ARROW_LEFT(cls="h-6 w-6")) if is_mobile else None,
                H3(cls='text-grey-darkest font-extrabold')(channel_name)
            ),
        ),
        Div(id=msgs_id, cls='scroller px-6 py-4 flex-1 flex flex-col-reverse overflow-y-scroll', style="padding-top: 60px; padding-bottom: 68px;" if is_mobile else "")(
            # lazy load first batch of messages
            Div(hx_trigger="load", hx_get=f"/c/messages/{cid}", hx_swap="outerHTML"),
        ), 
        Div(cls='pb-6 px-4 flex-none', style="position: fixed; bottom: 0; width: 100%; background-color: white;" if is_mobile else "")(
            Div(cls='flex rounded-lg border-2 border-grey overflow-hidden')(
                Span(cls='text-3xl text-grey border-r-2 border-grey p-2')(I_PLUS),
                Form(id=frm_id, cls="w-full", hx_post=f"/messages/send/{cid}", hx_target=f"#{msgs_id}", hx_swap="afterbegin",
                    **{ "hx-on::after-request": f"""document.querySelector("#{frm_id}").reset(); document.getElementById("{msgs_id}").scrollTop = document.getElementById("{msgs_id}").scrollHeight;""" }
                )(
                    Input(id='msg', autofocus="true", style="border:none; border-radius: 0;", placeholder=f"Message {channel_name}")
                ),
            )
        )
    ]

    return convo if req.headers.get('Hx-Request') else Layout(*convo, m=m, w=w, channel=channel, is_mobile=is_mobile)

@rt('/direct/{to_m}')
def direct(req: Request, to_m: int):
    # /direct?to=member
    # m wants to message to_m
    m, to_m = req.scope['m'], members[to_m]

    # check if direct channel already exists
    direct_channel = channels(where=f"is_direct=1 and id in (select channel from channel_member where member={m.id}) and id in (select channel from channel_member where member={to_m.id})")
    if len(direct_channel) != 0:
        direct_channel = direct_channel[0]
    else:
        direct_channel = channels.insert(Channel(name=f"{m.name}-{to_m.name}", workspace_id=m.workspace_id, is_direct=True))
        channel_members.insert(ChannelMember(channel=direct_channel.id, member=m.id))
        channel_members.insert(ChannelMember(channel=direct_channel.id, member=to_m.id))
    return RedirectResponse(f'/c/{direct_channel.id}', status_code=303)
    

def on_conn(ws, send):
    try:
        m, sid = members[int(ws.query_params.get("mid"))], str(id(ws))
        connections[sid] = send
        for s in sockets(where=f"mid={m.id}"): sockets.delete(s.sid)
        sockets.insert(Socket(sid=sid, mid=m.id))
    except NotFoundError: raise WebSocketException(400, "Missing member id")
    
def on_disconn(ws):
    sid = str(id(ws))
    try:
        sockets.delete(sid)
    except NotFoundError: pass
    connections.pop(sid, None)

async def process_ping(cmd: PingCommand, member: Member, current_channel: Channel):
    ChannelForMember.from_channel_member(channel_members(where=f"channel={cmd.cid} and member={member.id}")[0]).mark_all_as_read()
    await ws_send_to_member(member.id, ListOfChannelsForMember(member=member, current_channel=current_channel))

@app.ws('/ws', conn=on_conn, disconn=on_disconn)
async def ws(command:str, auth:dict, d: dict, ws, sess):
    print(f""" 
          Received socket message: {command}
          Auth is: {auth}
          Payload is: {d}
          Headers: {ws.headers}
          Session: {sess}""")

    mid, channel = int(auth['mid']), channels[int(d['cid'])]
    logger.debug(f"socket ID is {str(id(ws))}")
    
    try:
        socket = sockets[str(id(ws))]
    except NotFoundError:
        logger.debug(f"socket not found")
        return

    logger.debug(f"got socket {socket}")
    logger.debug(f"got command {command} with payload {json.dumps(d)}")
    
    cmd = Command.from_json(command, json.dumps(d))
    await { "ping": process_ping }[cmd.cmd](cmd, members[mid], channel)

serve()

## ================================ Tests

try:
    @pytest.fixture(scope="function", autouse=True)
    def create_test_database():
        setup_database(test=True)
        # yield
        # db.conn.close()

    @pytest.fixture()
    def client():
        yield Client(app)

    @pytest.fixture(scope="function", autouse=True)
    def create_test_application_server():
        # source: https://stackoverflow.com/a/64521239/320419
        class TestServer(uvicorn.Server):
            def install_signal_handlers(self): pass

            @contextlib.contextmanager
            def run_in_thread(self):
                t = threading.Thread(target=self.run)
                t.start()
                try:
                    while not self.started: time.sleep(1e-3)
                    yield
                finally:
                    self.should_exit = True
                    t.join()

        with TestServer(config=uvicorn.Config("app:app", host="0.0.0.0", port=5002, log_level="info")).run_in_thread(): yield

    def test_commands():
        cmd = Command.from_json("ping", '{"cid": 1}')
        assert isinstance(cmd, PingCommand) and cmd.cid == 1

    def test_healthcheck(client):
        response = client.get('/healthcheck')
        assert response.status_code == 200 and response.json() == {"status": "ok"}

    def test_auth(client):
        assert len(users()) == 1 and len(workspaces()) == 1 and len(channels()) == 2 and len(members()) == 1 and len(channel_members()) == 2

        response: Response = client.get('/')
        assert response.status_code == 200

        response = client.post('/login', data={"name": "Philip" })
        assert response.status_code == 303 and response.headers['location'] == '/c/1'
        assert len(users()) == 2 and len(members()) == 2 and len(channel_members()) == 4

    def test_message_seen(client):
        u1, u2, workspace = users.insert(User(name="Philip")), users.insert(User(name="John")), workspaces()[0]
        channel = channels.insert(Channel(name=f"{random.randint(1, 1000)}", workspace_id=workspace.id))
        m1, m2 = members.insert(Member(user_id=u1.id, workspace_id=workspace.id)), members.insert(Member(user_id=u2.id, workspace_id=workspace.id))
        cm1, cm2 = channel_members.insert(ChannelMember(channel=channel.id, member=m1.id)), channel_members.insert(ChannelMember(channel=channel.id, member=m2.id))

        # no messages in the channel
        assert channel.last_message_ts is None

        # user 1 sends message to the channel
        msg = channel_messages.insert(ChannelMessage(channel=channel.id, sender=m1.id, message="hello"))
        assert channel.last_message_ts == msg.created_at

        c4m1, c4m2 = ChannelForMember.from_channel_member(cm1), ChannelForMember.from_channel_member(cm2)

        assert c4m1.has_unread_messages is False and c4m2.has_unread_messages is True

        # sleep a bit (so timestamps work correctly)
        time.sleep(0.1)

        # user 2 sends a message to the channel, seen indicator should be updated
        channel_messages.insert(ChannelMessage(channel=channel.id, sender=m2.id, message="hey"))

        c4m1, c4m2 = ChannelForMember.from_channel_member(cm1), ChannelForMember.from_channel_member(cm2)

        assert c4m1.has_unread_messages is True and c4m2.has_unread_messages is False

        # can mark all as read
        c4m1 = c4m1.mark_all_as_read()

        assert c4m1.has_unread_messages is False

        # direct messages: steven messages philip
        client.post('/login', data={"name": "Steven"})

        u3 = users(where="name='Steven'")[0]
        m3 = members(where=f"user_id={u3.id}")[0]

        client.get(f'/direct/{m1.id}')

        assert len(channels(where="is_direct=1")) == 1

        direct_channel = channels(where="is_direct=1")[0]
        dc_members = channel_members(where=f"channel={direct_channel.id}")

        # no unread messages at first
        for dc_member in dc_members: assert ChannelForMember.from_channel_member(dc_member).has_unread_messages is False

        # steven marks all as read (via ping)
        assert dc_members[1].member == m3.id
        ChannelForMember.from_channel_member(dc_members[1]).mark_all_as_read()

        # double check list of channels for member
        c4m = ListOfChannelsForMember(member=m3, current_channel=channels()[0])

        assert len(c4m.direct_channels) == 1
        assert c4m.direct_channels[0].channel_member.member == m3.id
        assert c4m.direct_channels[0].has_unread_messages is False

        # check channels for philip
        c4m = ListOfChannelsForMember(member=m1, current_channel=channels()[0])

        assert len(c4m.direct_channels) == 1
        assert c4m.direct_channels[0].channel_member.member == m1.id
        assert c4m.direct_channels[0].has_unread_messages is False

        # philip sends a message
        channel_messages.insert(ChannelMessage(channel=direct_channel.id, sender=m1.id, message="hello"))

        # steven should have unread messages
        assert ChannelForMember.from_channel_member(dc_members[1]).has_unread_messages is True
        # philip should not
        assert ChannelForMember.from_channel_member(dc_members[0]).has_unread_messages is False

        # double check list of channels for member

        c4m = ListOfChannelsForMember(member=m3, current_channel=channels()[0])

        assert len(c4m.direct_channels) == 1
        assert c4m.direct_channels[0].channel_member.member == m3.id
        assert c4m.direct_channels[0].channel_name == "Philip"
        assert c4m.direct_channels[0].has_unread_messages is True
        
        c4m = ListOfChannelsForMember(member=m1, current_channel=channels()[0])

        assert len(c4m.direct_channels) == 1
        assert c4m.direct_channels[0].channel_member.member == m1.id
        assert c4m.direct_channels[0].channel_name == "Steven"
        assert c4m.direct_channels[0].has_unread_messages is False


    def test_direct_channel_setup(client):
        u1, workspace = users.insert(User(name="Philip")), workspaces()[0]
        m1 = members.insert(Member(user_id=u1.id, workspace_id=workspace.id))

        assert len(channels()) == 2 and len(channels(where="is_direct=1")) == 0

        # Bob registers (and logs in)
        client.post('/login', data={"name": "Bob"})

        u2 = users(where="name='Bob'")[0]
        m2 = members(where=f"user_id={u2.id}")[0]

        # Bob wants to message Philip
        client.get(f'/direct/{m1.id}')

        assert len(channels(where="is_direct=1")) == 1

        direct_channel = channels(where="is_direct=1")[0]

        assert direct_channel.name == "Bob-Philip"

        direct_channel_members = channel_members(where=f"channel={direct_channel.id}")

        assert len(direct_channel_members) == 2 and direct_channel_members[0].member == m1.id and direct_channel_members[1].member == m2.id

        # make sure new channel is not recreated
        client.get(f'/direct/{m1.id}')

        assert len(channels(where="is_direct=1")) == 1

    def test_list_of_channels_for_member(client):
        assert len(users()) == 1 and len(workspaces()) == 1 and len(channels()) == 2

        # philip signs up and logs in
        
        client.post('/login', data={"name": "Philip"})
        
        u1 = users(where="name='Philip'")[0]
        m1 = members(where=f"user_id={u1.id}")[0]

        c4m = ListOfChannelsForMember(member=m1, current_channel=channels()[0])

        assert len(c4m.group_channels) == 2 and len(c4m.direct_channels) == 0 and len(c4m.direct_channel_placeholders) == 1 and c4m.group_channels[0].channel_name == "general"
        assert c4m.group_channels[1].channel_name == "random"

        # bob signs up and logs in

        client.post('/login', data={"name": "Bob"})

        u2 = users(where="name='Bob'")[0]
        m2 = members(where=f"user_id={u2.id}")[0]

        c4m = ListOfChannelsForMember(member=m2, current_channel=channels()[0])

        assert len(c4m.group_channels) == 2 and len(c4m.direct_channels) == 0 and len(c4m.direct_channel_placeholders) == 2
        assert c4m.direct_channel_placeholders[0].member.name == "Phil"

        # bob wants to message philip

        client.get(f'/direct/{m1.id}')

        c4m = ListOfChannelsForMember(member=m2, current_channel=channels()[0])

        assert len(c4m.group_channels) == 2 and len(c4m.direct_channels) == 1 and len(c4m.direct_channel_placeholders) == 1
        assert c4m.direct_channels[0].channel_name == "Philip"

        # steven signs up and logs in

        client.post('/login', data={"name": "Steven"})

        u3 = users(where="name='Steven'")[0]
        m3 = members(where=f"user_id={u3.id}")[0]

        c4m = ListOfChannelsForMember(member=m3, current_channel=channels()[0])

        assert len(c4m.group_channels) == 2 and len(c4m.direct_channels) == 0 and len(c4m.direct_channel_placeholders) == 3

        assert c4m.direct_channel_placeholders[0].member.name == "Phil"
        assert c4m.direct_channel_placeholders[1].member.name == "Philip"

        # steven wants to message bob

        client.get(f'/direct/{m2.id}')

        c4m = ListOfChannelsForMember(member=m3, current_channel=channels()[0])

        assert len(c4m.group_channels) == 2 and len(c4m.direct_channels) == 1 and len(c4m.direct_channel_placeholders) == 2
        assert c4m.direct_channels[0].channel_name == "Bob" and c4m.direct_channel_placeholders[0].member.name == "Phil"

    def test_channel_message_pagination():
        # mess with cursor encoding/decoding

        t = get_ts()
        cursor = ChannelMessageWCtx.encode_cursor(t, "prev")
        assert ChannelMessageWCtx.decode_cursor(cursor) == (t, "prev")

        u, workspace, channel = users.insert(User(name="Philip")), workspaces()[0], channels()[0]
        m  = members.insert(Member(user_id=u.id, workspace_id=workspace.id))
        channel_members.insert(ChannelMember(channel=channel.id, member=m.id))

        assert len(channel_messages()) == 1200

        msg_batch, prev_cursor, next_cursor = ChannelMessageWCtx.fetch(channel.id)

        assert len(msg_batch) == settings.message_history_page_size
        assert msg_batch[0].message.startswith("1200")
        assert msg_batch[-1].message.startswith("1161")
        assert next_cursor is None
        assert prev_cursor is not None

        msg_batch, prev_cursor, next_cursor = ChannelMessageWCtx.fetch(channel.id, prev_cursor)

        assert len(msg_batch) == settings.message_history_page_size
        assert msg_batch[0].message.startswith("1160")
        assert next_cursor is not None
        assert prev_cursor is not None

    def test_happy_flow(page: Page):
        page.set_default_timeout(5000)
        page.goto("/login")

        page.get_by_placeholder("Name").fill(f"{random.randint(0, 1000000)}")
        page.get_by_role("button", name="Log in").click()

        # make sure we end up on the main channel page
        assert page.url.endswith("/c/1")

        # make sure message composer has focus
        assert page.get_by_placeholder("Message #general").evaluate("node => document.activeElement === node")

        page.wait_for_selector(".chat-message")

        assert page.locator(".chat-message").count() == settings.message_history_page_size
        assert page.locator(".chat-message").locator("nth=-1").locator("p").inner_html().startswith("1161")

        # scroll to the first message in the list
        page.locator(".chat-message").locator("nth=-1").scroll_into_view_if_needed()

        # expect more messages to load
        page.wait_for_selector(f".chat-message:nth-child({2 * settings.message_history_page_size})")
        assert page.locator(".chat-message").count() == 2 * settings.message_history_page_size
        assert page.locator(".chat-message").locator(f"nth={2 * settings.message_history_page_size - 1}").locator("p").inner_html().startswith("1121")

        # switch to "random" channel
        page.get_by_test_id("nav-to-channel-2").click()
        page.wait_for_url("**/c/2")

        # make sure message composer has focus
        # wait a bit for thing to settle
        page.wait_for_timeout(300)
        assert page.get_by_placeholder("Message #random").evaluate("node => document.activeElement === node")

        # send a message

        page.get_by_placeholder("Message #random").fill("hello world")
        page.get_by_placeholder("Message #random").press("Enter")

        page.wait_for_selector(".chat-message")
        assert page.locator(".chat-message").count() == 1

        page.locator(".chat-message").locator("p").inner_html().startswith("hello world")

        # logout
        page.get_by_test_id("profile-menu").click()
        page.get_by_test_id("logout").click()

        page.wait_for_url("**/")

    def test_messaging_interaction(playwright: Playwright, page: Page):
        base_url = "http://localhost:5002"
        browser = playwright.chromium.launch()
        
        steven_session, bob_session = browser.new_context(), browser.new_context()
        for s in [steven_session, bob_session]: s.set_default_timeout(5000)

        steven_page = steven_session.new_page()
        bob_page = bob_session.new_page()

        bob_page.goto(f"{base_url}/login")
        bob_page.get_by_placeholder("Name").fill("Bob")
        bob_page.get_by_role("button", name="Log in").click()
        
        bob_page.wait_for_url("**/c/1") 
        
        steven_page.goto(f"{base_url}/login")
        steven_page.get_by_placeholder("Name").fill("Steven")
        steven_page.get_by_role("button", name="Log in").click()
        
        steven_page.wait_for_load_state()

        assert steven_page.url.endswith("/c/1")

        # both steven and bob head to #random channel
        
        bob_page.goto(f"{base_url}/c/2")
        steven_page.goto(f"{base_url}/c/2")

        # steven sends a message
        steven_page.get_by_placeholder("Message #random").fill("hello world")
        steven_page.get_by_placeholder("Message #random").press("Enter")
        steven_page.wait_for_selector(".chat-message")
        steven_page.locator(".chat-message").locator("p").inner_html().startswith("hello world")

        # bob should see the message
        bob_page.wait_for_selector(".chat-message")

        assert bob_page.locator(".chat-message").count() == 1
        assert bob_page.locator(".chat-message").locator("p").inner_html() == "hello world"

        # bob responds

        bob_page.get_by_placeholder("Message #random").fill("hey there")
        bob_page.get_by_placeholder("Message #random").press("Enter")

        bob_page.wait_for_selector(".chat-message:nth-child(1)")
        assert bob_page.locator(".chat-message").count() == 2
        assert bob_page.locator(".chat-message:nth-child(1)").locator("p").inner_html() == "hey there"

        # steven should see the message
        steven_page.wait_for_selector(f".chat-message:nth-child(1)")
        assert steven_page.locator(".chat-message").count() == 2
        assert steven_page.locator(".chat-message:nth-child(1)").locator("p").inner_html() == "hey there"

        # check on new message indicator
        # everything in random channel should be marked as "read"
        expect(bob_page.get_by_test_id("nav-to-channel-2")).not_to_have_class(re.compile("has-unread-messages"))
        expect(steven_page.get_by_test_id("nav-to-channel-2")).not_to_have_class(re.compile("has-unread-messages"))

        # steven navigate to #general
        # bob sends a message on #random in the meantime

        steven_page.goto(f"{base_url}/c/1")
        steven_page.wait_for_url("**/c/1")

        bob_page.get_by_placeholder("Message #random").fill("sending another message to random")
        bob_page.get_by_placeholder("Message #random").press("Enter")

        # steven should see a new message notification for random channel

        expect(steven_page.get_by_test_id("nav-to-channel-2")).to_have_class(re.compile("has-unread-messages"))

        # steven navigates back to #random, sees the new message, and the notification is gone
        steven_page.goto(f"{base_url}/c/2")
        steven_page.wait_for_url("**/c/2")

        steven_page.wait_for_selector(".chat-message")
        assert steven_page.locator(".chat-message").count() == 3
        expect(steven_page.locator(".chat-message").locator("nth=0")).to_contain_text("sending another message to random")

        expect(steven_page.get_by_test_id("nav-to-channel-2")).not_to_have_class(re.compile("has-unread-messages"))

        # bob is going to DM steven now
        bob_page.get_by_test_id("dm-3").click()

        expect(bob_page.get_by_placeholder("Message Steven")).to_be_visible()
        expect(bob_page.get_by_test_id("dm-3")).to_have_count(0)

        # message steven
        bob_page.get_by_placeholder("Message Steven").fill("hello steven")
        bob_page.get_by_placeholder("Message Steven").press("Enter")

        # steven should see new message notification

        expect(steven_page.get_by_test_id("nav-to-channel-3")).to_contain_text("Bob")
        expect(steven_page.get_by_test_id("nav-to-channel-3")).to_have_class(re.compile("has-unread-messages"))

        # steven navigates to the DM channel

        steven_page.goto(f"{base_url}/c/3")
        steven_page.wait_for_url("**/c/3")

        steven_page.wait_for_selector(".chat-message")
        assert steven_page.locator(".chat-message").count() == 1
        assert steven_page.locator(".chat-message").locator("p").inner_html() == "hello steven"

        expect(steven_page.get_by_test_id("nav-to-channel-3")).not_to_have_class(re.compile("has-unread-messages"))

        # steven responds to bob

        steven_page.get_by_placeholder("Message Bob").fill("hey bob")
        steven_page.get_by_placeholder("Message Bob").press("Enter")

        # back to Bob now

        bob_page.wait_for_url("**/c/3")

        bob_page.wait_for_selector(".chat-message:nth-child(1)")
        assert bob_page.locator(".chat-message").count() == 2
        assert bob_page.locator(".chat-message:nth-child(1)").locator("p").inner_html() == "hey bob"

    def test_mobile(playwright: Playwright):
        base_url = "http://localhost:5002"
        browser = playwright.chromium.launch()    
        session = browser.new_context(**playwright.devices["iPhone 13"])

        page = session.new_page()
        page.goto(f"{base_url}/login")
        page.get_by_placeholder("Name").fill("Steven")
        page.get_by_role("button", name="Log in").click()

        page.wait_for_url("**/c/1")

        assert page.get_by_placeholder("Message #general").evaluate("node => document.activeElement === node")

        # confirm mobile sidebar toggler is visible
        expect(page.get_by_test_id("show-mobile-sidebar")).to_be_visible()

        page.get_by_test_id("show-mobile-sidebar").click()

        # navigate to #random
        page.get_by_test_id("nav-to-channel-2").click()

        page.wait_for_url("**/c/2")

        page.wait_for_timeout(300)
        assert page.get_by_placeholder("Message #random").evaluate("node => document.activeElement === node")

        # message random
        page.get_by_placeholder("Message #random").fill("hello world")
        page.get_by_placeholder("Message #random").press("Enter")

        page.wait_for_selector(".chat-message")
except: pass
