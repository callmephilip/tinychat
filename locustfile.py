from locust import HttpUser, task, between
from typing import Optional
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
        self.client.post('login', dict(name=get_random_user()))
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
    def send_message(self):
        upload = None
        if random.choice([0, 1, 2, 3]) == 3: upload = self.upload_file()
        payload = dict(msg=get_random_message())
        if upload: payload[f'upload_{upload}'] = upload
        self.client.post('messages/send/1', payload)
        if upload: self.client.get(f"download/{upload}")

    def upload_file(self) -> Optional[str]:
        file = ('image.jpeg', open('test-data/image.jpeg', 'rb'), 'image/jpeg')
        r = self.client.post("upload", files={'file': file}, headers={"Hx-Request": "true"})
        # what we get back looks like:
        # <input type="hidden" value="4b3f303a-d166-4f97-b2d5-bb5e11800d8d" name="upload_4b3f303a-d166-4f97-b2d5-bb5e11800d8d">
        # extract value and name
        m = re.search(r'value="[\w-]+"', r.text)
        if not m: return None
        return m.group().split('"')[1]

    @task
    def browse_chat_history(self):
        url = "/c/messages/1"
        for _ in range(random.randint(1, 20)):
            r = self.client.get(url, headers={"Hx-Request": "true"})
            m = re.search(r'hx-get="/c/messages/\d+\?c=[A-Za-z0-9+/=-]+"', r.text)
            if not m: return
            url = m.group().split('hx-get=')[1].replace('"', '')
