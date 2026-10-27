import math


def ceil_to_100(value):
    return int(math.ceil(float(value) / 100.0) * 100)


def parse_margin_ratio(value):
    if value is None:
        return None
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    ratio = float(text)
    if ratio >= 1:
        ratio /= 100.0
    return ratio


def parse_commission_percent(value):
    if value is None:
        return None
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    percent = float(text)
    if percent < 1:
        percent *= 100.0
    return percent


def calculate_base_payout(market_price, margin_rate):
    if market_price is None or margin_rate is None:
        return None
    market = float(market_price)
    rate = float(margin_rate)
    if rate >= 1:
        rate /= 100.0
    if rate < 0 or rate >= 1:
        return None
    return market / (1.0 - rate)


def final_sale_price(market_price, margin_rate, commission_percent):
    base_payout = calculate_base_payout(market_price, margin_rate)
    if base_payout is None:
        return None
    percent = float(commission_percent or 0.0)
    return ceil_to_100(base_payout / (1.0 - percent / 100.0))
