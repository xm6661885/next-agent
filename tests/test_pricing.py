from types import SimpleNamespace
from server.config import Price
from server.pricing import lookup, process_cost

def test_price_lookup_and_cumulative_usage():
    prices={'Opus':Price(input=5,output=25,cache_write=6.25,cache_read=.5)}
    assert lookup(prices,'opus[1m]')==prices['Opus']
    assert lookup(prices,'OPUS')==prices['Opus']
    usage={'OPUS[1m]':{'inputTokens':1000000,'outputTokens':200000,'cacheCreationInputTokens':100000,
                       'cacheReadInputTokens':300000,'costUSD':99},'unknown':{'costUSD':.7}}
    msg=SimpleNamespace(model_usage=usage,total_cost_usd=100)
    assert process_cost(msg,prices)==5+5+.625+.15+.7
    assert process_cost(SimpleNamespace(model_usage={},total_cost_usd=.8),prices)==.8
    assert process_cost(SimpleNamespace(model_usage=None,total_cost_usd=None),prices)==0
