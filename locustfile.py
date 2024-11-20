# locustfile.py
# For more options read the following
#   - https://docs.locust.io/en/stable/writing-a-locustfile.html
#   - https://docs.locust.io/en/stable/tasksets.html

from locust import HttpUser, task, between
import gevent, json
from websockets.sync.client import connect

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

    def ws_connect(self):
        session_cookie = self.client.cookies.get_dict().get('session_')
        self.ws = connect("ws://localhost:5001/ws?mid=3", additional_headers={"Cookie": f"session_={session_cookie}"})
        self.ws_greenlet = gevent.spawn(self.ws_receive_loop)
        self.ping_greenlet = gevent.spawn(self.ping_loop)
        
    def ws_receive_loop(self):
        while True:
            message = self.ws.recv()
            print(f"WS Received: {message}")

    def ping_loop(self):
        while True:
            self.ws.send(json.dumps({"cmd": "ping", "d": {"cid": 1}}))
            gevent.sleep(5)


    @task
    def chat(self):
        # User goes to the root of the project
        self.client.get('/')
        self.client.get('/login')
        self.client.post('/login', dict(name='locust'))
        self.client.post('messages/send/1', dict(msg='Hello, world!'))

        self.ws_connect()

        r = self.client.get('/c/1')
        assert r.status_code == 200
