from pybit import HTTP
from pybit.exceptions import InvalidRequestError
from datetime import datetime as dt

import numpy as np
import time

import config


def _print(message, level='info'):
    """
    Just a custom print function. Better than logging.
    """
    if level == 'position':
        print(f'{dt.utcnow()} - {message}.', end='\r')
    else:
        print(f'{dt.utcnow()} - {level.upper()} - {message}.')


def scale_qtys(x, n):
    """
    Will create a list of qtys on both long and short
    side that scale additively i.e.
    [5, 4, 3, 2, 1, -1, -2, -3, -4, -5].

    x: How much of your balance to use.
    n: Number of orders.
    """

    n_ = x / ((n + n ** 2) / 2)
    if n_ < 1:
        _print("You need more equity to make this work, setting it to the minimum")
        n_ = 1
    long_qtys = [int(n_ * i) for i in reversed(range(1, n + 1))]
    short_qtys = [-i for i in long_qtys]
    return long_qtys + short_qtys[::-1]

def prepare_orders(qtys) -> object:
    orders = [
        {
            'symbol': config.SYMBOL,
            'side': 'Buy' if qtys[k] > 0 else 'Sell',
            'order_type': 'Limit',
            'qty': abs(qtys[k]),
            'price': int(prices[k]),
            'time_in_force': 'GoodTillCancel',
        } for k in range(len(qtys))
    ]
    return orders
    _print('Submitting orders')

if __name__ == '__main__':
    # print('\n--- SAMPLE MARKET MAKER V2 ---')
    # print('For pybit, created by verata_veritatis.')
    # print('For pybit, modified by xbrandonx.')

    if not config.API_KEY or not config.PRIVATE_KEY or not config.ENDPOINT:
        raise PermissionError('An API key and endpoint is required to run this program.')

    print('\nUSE AT YOUR OWN RISK!!!\n')

    _print('Opening session')
    s = HTTP(
        api_key=config.API_KEY,
        api_secret=config.PRIVATE_KEY,
        endpoint=config.ENDPOINT,
        logging_level=50,
        retry_codes={10002, 10006},
        ignore_codes={20001, 30034},
        force_retry=True,
        max_retries=10,
        retry_delay=15
    )
    # Adjust as required above
    
    # Auth sanity test.
    try:
        s.get_wallet_balance()
    except InvalidRequestError as e:
        raise PermissionError('API key is invalid.')
    else:
        _print('Authenticated sanity check passed')

    # Set leverage to cross.
    try:
        s.set_leverage(
            symbol=config.SYMBOL,
            leverage=0
        )
    except InvalidRequestError as e:
        if e.status_code == 34015:
            _print('Margin is already set to cross')
    else:
        _print('Forced cross margin')

    print('\n------------------------------\n')

    # Main loop.
    while True:

        # Cancel orders.
        s.cancel_all_active_orders(
            symbol=config.SYMBOL
        )

        # REMOVED. We are going to perpetually check for a position AND orders using a timer.
        # Close position if open.
        # s.close_position(
        #    symbol=config.SYMBOL
        # )

        # Grab the last price.
        _print('Checking last price')
        last = float(s.latest_information_for_symbol(
            symbol=config.SYMBOL
        )['result'][0]['last_price'])
        _print(last)

        # Grab the position size
        _print('Checking position price')
        position = float(s.my_position(
            symbol=config.SYMBOL
        )['result']['entry_price'])
        _print('Checked position price')

        price_range = config.RANGE * last
        # Create order price span.
        _print('Generating order prices')
        prices = np.linspace(
            last - price_range / 2, last + price_range / 2, config.NUM_ORDERS * 2
        )

        if position:
            _print('YES THERE IS A POSITION')
            price_range = config.RANGE * last
            # Create order price span.
            _print('Generating TP price around last price')

            if s.my_position(
                    symbol=config.SYMBOL
            )['result']['side'] == 'Sell':
                _print('Set Take Profit on Sell Position')
                tp_dp = config.TP_DIST * position
            elif s.my_position(
                    symbol=config.SYMBOL
            )['result']['side'] == 'Buy':
                _print('Set Take Profit on Buy Position')
                tp_dp = config.TP_DIST * position
        else:
            _print('NO POSITION')
            tp_dp = config.TP_DIST * last

        # price_range = config.RANGE * last
        # moved up

        #############################################################################
        # Scale quantity additively (1x, 2x, 3x, 4x).
        _print('Generating order quantities')
        balance_in_usd = float(s.get_wallet_balance(
            coin=config.COIN
        )['result'][config.COIN]['available_balance']) * last
        available_equity = balance_in_usd * config.EQUITY
        qtys = scale_qtys(available_equity, config.NUM_ORDERS)

        # NEED TO CHECK FOR ZERO QTY ORDERS !!!!!!!!!!!!!!!!!!!

        #############################################################################
        # Prepare orders.
        orders = prepare_orders(qtys)
        responses = s.place_active_order_bulk(orders=orders)
        _print('Prepared order quantities')

        #############################################################################
        # Let's create an ID list of buys and sells as a dict.
        _print('Orders submitted successfully')
        order_ids = {
            'Buy': [i['result']['order_id']
                    for i in responses if i['result']['side'] == 'Buy'],
            'Sell': [i['result']['order_id']
                     for i in responses if i['result']['side'] == 'Sell'],
        }

        #############################################################################
        # In-position loop.
        while True:

            start = time.time()
            print("Clock is:")
            print(start)

            # Await position.
            _print('Awaiting Fireworks')
            while not abs(s.my_position(
                    symbol=config.SYMBOL
            )['result']['size']):
                time.sleep(1 / config.POLLING_RATE)

            #############################################################################
            # When we have a position, get the size and cancel all the
            # opposing orders.
            if s.my_position(
                    symbol=config.SYMBOL
            )['result']['side'] == 'Buy':
                to_cancel = [{
                    'symbol': config.SYMBOL,
                    'order_id': i
                } for i in order_ids['Sell']]
            elif s.my_position(
                    symbol=config.SYMBOL
            )['result']['side'] == 'Sell':
                to_cancel = [{
                    'symbol': config.SYMBOL,
                    'order_id': i
                } for i in order_ids['Buy']]
            else:
                #############################################################################
                # Position was closed immediately for some reason. Restart.
                _print('Position closed unexpectedly—resetting')
                break

            # time.sleep(1)
            s.cancel_active_order_bulk(
                orders=to_cancel
            )
            # modify to cancel all orders, not just a list
            # s.cancel_all_active_orders
            # time.sleep(1)

            #############################################################################
            # Set a TP.
            p = s.my_position(symbol=config.SYMBOL)['result']
            e = float(p['entry_price'])
            tp_response = s.place_active_order(
                symbol=config.SYMBOL,
                side='Sell' if p['side'] == 'Buy' else 'Buy',
                order_type='Limit',
                qty=p['size'],
                price=int(e + tp_dp if p['side'] == 'Buy' else e - tp_dp),
                time_in_force='GoodTillCancel',
                reduce_only=True
            )
            curr_size = p['size']
            _print('TP has been set to:')

            #############################################################################
            # Set a position stop.
            # time.sleep(1)
            if config.STOP_DIST:
                e = float(p['entry_price'])
                if p['side'] == 'Buy':
                    stop_price = e - (e * config.STOP_DIST)
                    _print('Setting Buy Side Stop')
                    _print(stop_price)
                else:
                    stop_price = e + (e * config.STOP_DIST)
                    _print('Setting Sell Side Stop')
                    _print(stop_price)
                s.set_trading_stop(
                    symbol=config.SYMBOL,
                    stop_loss=int(stop_price)
                )

            #############################################################################
            # Monitor position.
            print('\n------------------------------\n')
            while p['size']:

                #############################################################################
                # Get the size with sign based on side.
                sign = p['size'] if p['side'] == 'Buy' else -p['size']
                pnl_sign = '+' if float(p['unrealised_pnl']) > 0 else '-'

                #############################################################################
                # Show status.
                _print(
                    f'Size: {sign} ({float(p["effective_leverage"]):.2f}x), '
                    f'Entry: {float(p["entry_price"]):.2f}, '
                    f'Balance: {float(p["wallet_balance"]):.8f}, '
                    f'PNL: {pnl_sign}{abs(float(p["unrealised_pnl"])):.8f}',
                    level='position'
                )

                #############################################################################
                # Sleep and re-fetch.
                time.sleep(1 / config.POLLING_RATE)
                p = s.my_position(symbol=config.SYMBOL)['result']

                #############################################################################
                # If size has changed, update TP based on entry and size.
                if p['size'] > curr_size:
                    e = float(p['entry_price'])
                    tp_price = e + tp_dp if p['side'] == 'Buy' else e - tp_dp
                    s.replace_active_order(
                        symbol=config.SYMBOL,
                        order_id=tp_response['result']['order_id'],
                        p_r_price=int(tp_price),
                        p_r_qty=p['size']
                    )
                    curr_size = p['size']

                #############################################################################
                # If all orders have been filled create a new batch and place on the correct side
                # code to follow

                #############################################################################
                # If an elapsed time has expired reset and place a new batch of orders
                # Configure time in config
                current = time.time()
                elapsed = current - start
                print(elapsed)
                if elapsed > config.TIMETOWAIT:
                    break

            #############################################################################
            # Position has closed—get PNL information.
            print(' ' * 120, end='\r')
            pnl_r = s.closed_profit_and_loss(
                symbol=config.SYMBOL
            )['result']['data'][0]

            #############################################################################
            # Store PNL data as string.
            side = 'Buy' if pnl_r['side'].lower() == 'sell' else 'Sell'
            pos = f'{side} {pnl_r["qty"]}'
            prc = f'{pnl_r["avg_entry_price"]} -> {pnl_r["avg_exit_price"]}'

            #############################################################################
            # Display PNL info.
            _print(f'Position closed successfully: {pos} ({prc})')
            print('\n------------------------------\n')
            break
