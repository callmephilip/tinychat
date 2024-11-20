# locustfile.py
# For more options read the following
#   - https://docs.locust.io/en/stable/writing-a-locustfile.html
#   - https://docs.locust.io/en/stable/tasksets.html

from locust import HttpUser, task, between
import gevent, json, re 
from websockets.sync.client import connect

user_cnt: int = 0

class TinychatUser(HttpUser):
    """
    This class represents simulated users interacting with
    a website.
    """
    # What tasks should be done    
    # tasks = [TaskSet]
    # how long between clicks a user should take
    wait_time = between(2, 20)
    # The default host of the target client. This can be changed
    # at any time
    host = 'http://localhost:5001/'

    def on_start(self):
        global user_cnt
        user_cnt += 1
        self.client.post('/login', dict(name=f'locust-{user_cnt}'))
        self.ws_connect()
    
    def on_stop(self):
        print(">>>>>>>>>>>>>>>>>>>>>>>> Stopping user >>>>>>>>>>>>>>>>>>>>>>>")

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
        self.client.post('messages/send/1', dict(msg='Hello, world!'))
        assert self.client.get('/c/1').status_code == 200

    @task
    def browse_chat_history(self):
        url = "/c/messages/1"
        
        for _ in range(5):
            r = self.client.get(url, headers={"Hx-Request": "true"})
            m = re.search(r'hx-get="/c/messages/\d+\?c=[A-Za-z0-9+/=-]+"', r.text)
            if not m: return
            url = m.group().split('hx-get=')[1].replace('"', '')