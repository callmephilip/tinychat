from locust import HttpUser, task, between
import gevent, json, re, random
from websockets.sync.client import connect

messages = []
users = []

def get_random_message():
    global messages
    if not messages:
        with open("test-data/messages.txt", 'r', encoding='utf-8') as file: messages = [l.strip() for l in file.readlines() if l.strip()]
    return random.choice(messages)

def get_random_user():
    global users
    if not users:
        with open("test-data/users.txt", 'r', encoding='utf-8') as file: users = [l.strip() for l in file.readlines() if l.strip()]
    return random.choice(users)

class TinychatUser(HttpUser):
    """
    This class represents simulated users interacting with
    a website.
    """
    # What tasks should be done    
    # tasks = [TaskSet]
    # how long between clicks a user should take
    wait_time = between(1, 5)
    # The default host of the target client. This can be changed
    # at any time
    host = 'http://localhost:5001/'

    def on_start(self):
        self.client.post('/login', dict(name=get_random_user()))
        self.ws_connect()
    
    def on_stop(self):
        pass

    def ws_connect(self):
        session_cookie = self.client.cookies.get_dict().get('session_')
        self.ws = connect("ws://localhost:5001/ws?mid=3", additional_headers={"Cookie": f"session_={session_cookie}"})
        self.ws_greenlet = gevent.spawn(self.ws_receive_loop)
        self.ping_greenlet = gevent.spawn(self.ping_loop)
        
    def ws_receive_loop(self):
        while True:
            self.ws.recv()
            print(f"** WS Received data")

    def ping_loop(self):
        while True:
            self.ws.send(json.dumps({"cmd": "ping", "d": {"cid": 1}}))
            gevent.sleep(5)

    @task
    def chat(self):
        self.client.post('messages/send/1', dict(msg=get_random_message()))
        assert self.client.get('/c/1').status_code == 200

    @task
    def browse_chat_history(self):
        url = "/c/messages/1"
        for _ in range(random.randint(1, 20)):
            r = self.client.get(url, headers={"Hx-Request": "true"})
            m = re.search(r'hx-get="/c/messages/\d+\?c=[A-Za-z0-9+/=-]+"', r.text)
            if not m: return
            url = m.group().split('hx-get=')[1].replace('"', '')
