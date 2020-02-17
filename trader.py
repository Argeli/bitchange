import time
import ccxt
import math
import keys
#import ccxt.async_support as ccxt

class Trader:
    """Trading class (where the magic happens)"""

    def __init__(self):
        """Catalogue of params"""
        self.kraken_public = keys.kraken_public
        self.kraken_private = keys.kraken_private
        self.binance_public = keys.binance_public
        self.binance_private = keys.binance_private

        self.exchange = {}
        self.market = {}
        self.ticker = {}
        self.balance = {}
        self.balance_init = {}
        self.tidy_balance = {}

        self.amnt_precision = 0
        self.amnt_min = 0
        self.price_precision = 0
        self.cost_min = 0
        self.base_precision = 0
        self.quote_precicion = 0

        self.latest_best_bidask = []
        self.latest_avg_bidask =  []
        self.latest_value = 0

        self.too_low = False
        self.grid_center = 0
        self.grid_nb = 0        #The n-th grid
        self.grid_start_time = 0
        self.last_order = 0
        self.stoploss = False
        self.top_exit = False
        self.amnt_incr = 0

        self.order = {}
        self.order_data = ""
        self.traded = False

        #Parameters
        self.market_ident = 'XRP/BTC'
        self.order_type = "market"
        self.market_split = self.market_ident.split("/")
        self.grid_range = 0.03  #Half range
        self.grid_count = 20    #Full range


    def set_up(self):
        """Set_up main parameters for trader instance"""
        # self.exchange = ccxt.kraken({
        #     'apiKey': self.kraken_public,
        #     'secret': self.kraken_private,
        #     'enableRateLimit': True                 #ccxt internal limit failsafe for avoiding ban on exchange
        # })
        self.exchange = ccxt.binance({
            'apiKey': self.binance_public,
            'secret': self.binance_private,
            'enableRateLimit': True                 #ccxt internal limit failsafe for avoiding ban on exchange
        })

        self.exchange.load_markets()
        self.market = self.exchange.markets[self.market_ident]

        self.amnt_precision = self.market['precision']['amount']
        self.amnt_min = self.market['limits']['amount']['min']
        self.cost_min = self.market['limits']['cost']['min']
        self.price_precision = self.market['precision']['price']
        self.base_precision = self.market['precision']['base']
        self.quote_precision = self.market['precision']['quote']


    def set_up_grid(self):
        """Set up and buy into a grid"""
        self.ticker = self.exchange.fetch_ticker(self.market_ident)        #fetching 24h stats on market, heavy call
        self.grid_center = self.ticker['last']
        self.last_order = self.grid_center
        self.latest_value = self.grid_center
        self.update_balance()
        self.balance_init = self.balance
        self.amnt_incr = self.balance['Total (base)'] / self.grid_count
        self.grid_start_time = time.time()
        self.buy_in_out("in")
        self.update_balance()


    def trade(self):
        """Main trading method. Returns of internal method calls are listed for debug help"""

        self.update_bidask()

        #Compute movement on grid
        grid_jumps = int(self.grid_count * abs(self.latest_value - self.last_order) \
                         / (2 * self.grid_range * self.grid_center))
        value_increased = self.latest_value - self.last_order > 0
        to_sell = self.market_split[1 - value_increased]

        #Compute amount and price to sell/buy
        amount = grid_jumps * self.amnt_incr
        price = self.latest_value
        #price = (self.latest_best_bidask[value_increased]
        #         + self.latest_avg_bidask[value_increased]) / 2    #not fair enough
        budget = self.balance[to_sell] if value_increased else \
            self.balance[to_sell] / self.latest_value

        sane_amount, sane_price= self.sanitize_and_flag(amount, price, budget)

        if not(self.stoploss) and not(self.too_low):
            #Open order if values are sane and no stoploss (ground exit of grid)
            self.order = self.exchange.create_order(self.market_ident,
                                               self.order_type,
                                               ['buy', 'sell'][value_increased],
                                               sane_amount,
                                               sane_price if self.order_type == "limit" else None)
            self.traded = True
            self.last_order = self.latest_value

            #Top exit of grid
            #if self.top_exit:
                # self.grid_center = self.last_order
                # self.amnt_incr = self.balance['Total (base)'] / self.grid_count
                # self.grid_start_time = time.time()
                # self.grid_nb += 1

        else:
            if self.too_low:
                self.too_low_data = f"Skipped trading round: cost or amount too low \
                                      \nCost: {sane_price * sane_amount}            \
                                       | Amount: {sane_amount}                      \
                                      \nLast order: {self.last_order}               \
                                       | Latest_value: {self.latest_value}"
                self.traded = False

        self.update_balance()
        self.order_data = self.data_format(sane_amount, sane_price, value_increased, grid_jumps)
        time.sleep(10)


    def update_balance(self):
        """Update and format balance to present data"""
        self.balance = self.exchange.fetch_balance()['total']
        total_budget = self.balance[self.market_split[0]] + self.balance[self.market_split[1]] / self.latest_value
        self.balance['Total (base)'] = float(round(total_budget, self.base_precision))
        self.balance['Total (quote)'] = float(round(total_budget * self.latest_value, self.quote_precision))
        self.tidy_balance = {k: v for k, v in self.balance.items() if k in self.market_split + ['Total (base)', 'Total (quote)'] }


    def update_bidask(self):
        """Update latest value and bidask. Avg ask and bid are weighted by volume.
        Standard depth is 100 orders"""

        latest_bids = self.exchange.fetch_order_book(self.market_ident)['bids']
        latest_avg_bid = sum([bid * volume for [bid, volume] in latest_bids]) \
                          / sum([volume for [bid, volume] in latest_bids])

        latest_asks = self.exchange.fetch_order_book(self.market_ident)['asks']
        latest_avg_ask = sum([ask * volume for [ask, volume] in latest_asks]) \
                          / sum([volume for [ask, volume] in latest_asks])

        self.latest_avg_bidask = [latest_avg_bid, latest_avg_ask]
        self.latest_best_bidask = [latest_bids[0][0], latest_asks[0][0]]

        #Value is calculated as simple avg of avg bid and ask
        self.latest_value = (latest_avg_bid + latest_avg_ask) / 2


    def sanitize_and_flag(self, amount, price, budget):
        """Verify and enforce compatibilities of values with exchange api norms"""
        #Force good precision
        sane_amount = float(round(amount, self.amnt_precision))
        sane_amount = min(math.trunc(budget * 10**self.amnt_precision) / 10**self.amnt_precision, sane_amount)      #truncate only because of budget limit. Else : round to closest
        sane_price = float(round(price, self.price_precision))

        #Check if amount or cost is too small
        self.too_low = (self.amnt_min > sane_amount) or (self.cost_min > sane_price * sane_amount)

        self.stoploss = self.latest_value < self.grid_center * (1 - self.grid_range)
        self.top_exit = self.latest_value > self.grid_center * (1 + self.grid_range)

        return sane_amount, sane_price


    def data_format(self, sane_amount, sane_price, value_increased, grid_jumps):
        """Computation and formatting of data for last order"""
        tot_evol = (self.balance['Total (quote)'] - self.balance_init['Total (quote)']) \
            / self.balance_init['Total (quote)']
        tot_evol = float(round(100 * tot_evol, 2))

        position = (self.last_order - self.grid_center) / (self.grid_center * self.grid_range)
        position = float(round(100 * position, 2))

        grid_pos =  int(self.grid_count * abs(self.latest_value - self.grid_center)                 \
                         / (2 * self.grid_range * self.grid_center))
        proj_null_total = self.balance['Total (quote)'] * self.grid_center / self.latest_value      \
            + (grid_pos - 1) * self.amnt_incr * self.grid_center                                    \
            * grid_pos * self.grid_range / (2 * self.grid_count)
        proj_null = (proj_null_total - self.balance_init['Total (quote)'])                          \
            / self.balance_init['Total (quote)']
        proj_null = float(round(100 * proj_null, 2))
        
        order_data = ("---Last Trading Round---\n" + "Wallet is: " + str(self.tidy_balance)
                    + f"\nGrid number: {self.grid_nb} | Time: "
                    + time.strftime("%H:%M:%S", time.gmtime(time.time() - self.grid_start_time))
                    + "\nOrder: " + ['buy', 'sell'][value_increased] + f" {sane_amount}"
                    + f" of {self.market_ident} for {sane_price}"
                    + f"\nJumps: {grid_jumps} | Position: {position}%"
                    + f"\nAbsolute total return: {tot_evol}%"
                    + f"| Projected: stable {proj_null}% bad ")

        return order_data


    def buy_in_out(self, in_out = "in"):
        """Buy in or out of base currency when entering or escaping a grid"""
        in_out = {'in': 1, 'out': 0}[in_out]
        self.update_balance()
        self.update_bidask()

        #Compute amount and price
        if in_out:
            x = self.balance[self.market_split[0]]                      #where market_ident ~ x/y (base/quote)
            y = self.balance[self.market_split[1]] / self.latest_value
            mean = (x + y) / 2
            amount = abs(x - mean)
            whatdo = ['sell', 'buy'][x < mean]
            budget = self.balance[self.market_split[0]] if x > mean else \
                self.balance[self.market_split[1]] / self.latest_value

        else:
            budget = self.balance[self.market_split[0]]
            amount = self.balance[self.market_split[0]]

        price = self.latest_value
        sane_amount, sane_price = self.sanitize_and_flag(amount, price, budget)
        if not(self.too_low):
            #Open order if values are sane
            self.order = self.exchange.create_order(self.market_ident,
                                               self.order_type,
                                               whatdo if in_out else 'sell',
                                               sane_amount,
                                               sane_price if self.order_type == "limit" else None)
            self.last_order = self.latest_value
            if not(in_out):
                self.update_balance()
                self.order_data = self.data_format(sane_amount, sane_price, 1, "-buy out-")
            else:
                self.order_data = self.data_format(sane_amount, sane_price, 1, "-buy in-")
        else:
            self.order_data = "--- No buy in/out trade necessary---"
            self.order = {}
