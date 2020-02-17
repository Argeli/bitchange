import requests
import keys

class Speaker:
    """Speaker class which interfaces with the Telegram api"""
    
    def __init__(self):

        #tele stands for Telegram
        self.tele_token = keys.telegram_token
        self.tele_url = "https://api.telegram.org/bot" + self.tele_token
        self.tele_chatid = keys.telegram_chatid
        self.tele_last_msg_id = float("inf")        #Last unread msg should not be parsed (see listen())
        
        self.to_exe = False
        self.msg = ""
        self.received = False
        
    def listen(self):
        answer = requests.post(self.tele_url + "/getUpdates?timeout=60").json()
        
        #get last message or take an empty one
        last_msg = answer['result'][-1] if len(answer) > 0 else {'update_id' : 0}   
    
        if self.tele_last_msg_id < last_msg['update_id']:
            self.received = True
            command = last_msg['message']['text']
            
            if command.split(" ")[0] == "Get":
                self.to_exe = False
                self.msg =  command.split(" ")[1]
                
            else:
                self.to_exe = True
                self.msg = command
        else:
            self.received = False
            
        self.tele_last_msg_id = last_msg['update_id']
        
        return answer
    
    
    def send(self, msg):
        """Telegram message sender"""
        data = {'chat_id' : self.tele_chatid, 'text' : msg}
        requests.post(self.tele_url + "/sendMessage", data)