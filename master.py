import threading
import os
import logging
import time
import datetime
from matplotlib import pyplot as plt

from logger import setup_logger
import trader
import speaker
import keys

PATH = os.path.dirname(__file__)

#define main agent class. Speaker and Trader classes (see other files) are attributes of master
class Agent:
    """The Agent carries all information for Telegramm and trading apis.
    This File contains all general parameters and methods.
    3 threads run for trading (over ccxt), message sending and message receiving (over Telegram)"""
    
    def __init__(self, name):
        
        self.name = name

        self.trader = trader.Trader()
        self.speaker = speaker.Speaker()

        self.trader.binance_public = keys.binance_public
        self.trader.binance_private = keys.binance_private
        self.speaker.tele_token = keys.telegram_token
        self.speaker.tele_chatid = keys.telegram_chatid
            
        self.state = "shut down"  #Other states : "sleeping" (only listening) and "awake" (listening, trading and sending updates)
        
        #Set-up loggers
        self.error_log = setup_logger("Error logger", PATH + '\\error_log.txt', logging.ERROR)
        self.trade_log = setup_logger("Trade logger", PATH + '\\trade_log.txt', logging.INFO)
        
        self.listening_thread = None
        self.sending_thread = None
        self.trading_thread = None
        self.listening = False
        self.trading = False
        self.sending = False
        self.verbose = True
        self.show_too_low = False

        
        self.commands = {'Go sleep' : self.go_sleep,
               'Wake up!': self.wake_up,
               'Shutdown': self.shut_down,
               'Talk to me': self.set_verbose,
               'Be quiet': self.set_verbose,
               'Last trade': self.last_trade,
               'Show too low': self.set_show_too_low,
               'You alright?': self.get_state,
               'Get <attribute>': None}


    def set_up(self):
        """Set up the interface with trading exchange"""
        self.trader.set_up()
        self.listening_thread = threading.Thread(None, self.listening_loop, "Listening Thread")
        self.listening_thread.start()
        self.short_send("All is set up. Standing by.")
        self.state = "sleeping"


    def wake_up(self):
        """Wake up agent / set up and buy into grid / start trading and automatic non-verbose update"""
        self.short_send("Waking up..")
        
        if self.sending_thread != None and self.sending_thread.is_alive():      #Sending thread can stay alive whuile sleeping because of long time.sleep in loop
            self.sending = True
        else:
            self.sending_thread = threading.Thread(None, self.sending_loop, "Sending Thread")
            self.sending_thread.start()
            
        self.trading_thread = threading.Thread(None, self.trading_loop, "Trading Thread")
        self.trading_thread.start()
        self.state = "awake"
        

    def trading_loop(self):
        """Trade on exchange using ccxt, sleep is in self.trade()
        To be looped in thread"""
        self.trading = True
        self.trader.set_up_grid()
        self.short_send(f"Bought into grid_center: {self.trader.grid_center}\
                        \n---> Begin to trade\
                        \nWallet: {self.trader.tidy_balance}")
        self.trade_log.info(self.trader.order_data + f"\n-Order data:-\n{self.trader.order}\n")
        while self.trading:
            try:
                self.trader.trade()
                
                if self.trader.traded:    
                    self.trade_log.info(self.trader.order_data + "\n-Order data:-\n" + str(self.trader.order)) 
                    if self.verbose: self.short_send(self.trader.order_data)  
                    
                elif self.trader.stoploss or self.trader.top_exit:
                    self.go_sleep("---Shutting down due to grid exit---")
                    
                elif self.show_too_low:
                    self.short_send(self.trader.too_low_data)
                    
            except Exception as e:
                self.error_log.error(f"Error while trading with exchange api:\n{e}\n")
                self.go_sleep("Error while trading.")


    def listening_loop(self):
        """Telegram listener and msg handler. Using long polling for update retrieval.
        To be looped in thread"""
        self.listening = True
        while self.listening:
            try:
                answer = self.speaker.listen()
                
                if self.speaker.received:
                    
                    try:
                        if self.speaker.to_exe: 
                            self.commands[self.speaker.msg]()
                            
                        else:
                            value = eval(self.name + f".{self.speaker.msg}")
                            self.short_send(self.name + f".{self.speaker.msg} = {value}")
                            
                    except Exception as e:
                        if e == f"'{self.speaker.msg}'": e = ""         #Don't show e if it's a mispell in msg
                        self.short_send(f"You're miserable")
                                         
            except Exception as e:
                self.error_log.error(f"Error while getting updates from Telegram bot:\n{e}\
                                     \nTelegram request returned:\n{answer}\n")
                self.shut_down("Error while listening.")
                self.listening = False


    def sending_loop(self):
        """Thread fucntion for sending automatic updates. To be looped in thread"""
        self.sending = True
        while self.sending:
            update = "---Automatic Update---\n" + self.trader.order_data
            if not(self.verbose): self.short_send(update)
            time.sleep(3600)

    def set_show_too_low(self):
        self.short_send("Understood")
        self.show_too_low = not(self.show_too_low)
    
    
    def last_trade(self):
        self.short_send(self.trader.order_data)
        

    def set_verbose(self):
        self.short_send("Understood")
        self.verbose = not(self.verbose)
        
    def short_send(self, msg):
        try:
            self.speaker.send(msg)
        except Exception as e:
            self.error_log.error(f"Error while sending to Telegram:\n{e}\n")
            self.go_sleep("Error while sending.")

    def get_state(self):
        self.short_send("I'm " + self.state)
        self.short_send("""Do you want me to : 
                  Go sleep,\
                  Wake up!,\
                  Shutdown,\
                  Show too low,\
                  Talk to me (verbose),\
                  Get <attribute>,\
                  Last trade or\
                  Be quiet (verbose) ?""")
                  
                  
    def buy_out(self):
        """Buy out of grid"""
        try:
            self.trader.buy_in_out("out")
            self.trade_log.info(self.trader.order_data + "\n-Order data:-\n" + str(self.trader.order)) 
            self.short_send(self.trader.order_data) 
            
            #package trade_log of last grid
            self.trade_log.handlers[0].close()
            now = datetime.datetime.now().strftime("%H%M%S_%d%m%y")
            runtime = time.strftime("%H%M%S", time.gmtime(time.time() - self.trader.grid_start_time))
            os.rename(PATH + '\\trade_log.txt',
                      PATH + f'\\trade_log_{self.trader.market_ident}_closed_on_{now}'.replace("/", "-")
                      + f'_ran_for_{runtime}.txt')
            
        except Exception as e:
            self.error_log.error(f"Error with exchange api while trying to buy out:\n{e}\n")


    def go_sleep(self, msg=""):
        self.trading = False
        self.sending = False
        try:
            self.speaker.send("Going to sleep.. " + msg)         #.speaker method called to escape debug loop
        except Exception as e:
            self.error_log.error(f"Error while sending 'going to sleep msg':\n{e}\n")
        time.sleep(5)       #making sure there is no last order running and interfering with buy out
        self.buy_out()
        self.state = "sleeping"


    def shut_down(self, msg=""):
        self.trading = False
        self.sending = False
        self.listening = False
        self.speaker.tele_last_msg_id = float("inf")
        try:
            self.speaker.send("Shutting down: " + msg)      #.speaker method called to escape debug loop
        except Exception as e:
            self.error_log.error(f"Error while sending 'shutting down msg':\n{e}\n")
        self.buy_out()
        self.state = "shut down"

def session_analysis(filename):
    """Analyse trade returns from last session. EN COURS"""
    trade_log = open(PATH + f"/{filename}.txt", 'r')
    time_list, return_list, price_list = [], [], []
    for line in trade_log:
        if "| Time:" in line:
            time = line.split("| Time: ")[1].split(":")
            sec = 3600 * float(time[0]) + 60 * float(time[1]) + float(time[2][:-2])
            time_list.append(sec)
        elif "| Total return:" in line:
            return_list.append(float(line.split("| Total return: ")[1][:-2]))
        elif "ETH/BTC for" in line:
            price = float(line.split("ETH/BTC for ")[1][:-2])
            price_list.append(price)
    start = return_list.index(-0.05)
    fig, subplot1 = plt.subplots()
    subplot1.plot(time_list[start:], return_list[start:])
    subplot2 = subplot1.twinx()
    subplot2.plot(time_list[start:], price_list[start:], 'r')
    plt.show()
#session_analysis('trade_log5')            
    
    
if __name__ == '__main__':
    smith = Agent("smith")
    smith.set_up()
    #smith.wake_up()

