import yfinance as yf
import time

# stock_list = ['AMGN', 'AZO', 'WMT', 'WM', 'GLD', 'TLT']
stock_list = ['AZO', 'ORLY']

period_ = "25Y"

for ticker in stock_list:
    spy = yf.Ticker(ticker)
    data = spy.history(period=period_, actions=True)

    file_full_path = f"US MKT Raw Data/{ticker}_{period_}_yFinance.csv"
    data.to_csv(file_full_path)

    print(data.tail())
    print(ticker, ' process done')

    time.sleep(3)

