"""Calculate CLI process cost with optional model prices."""
import re

SUFFIX = re.compile(r'\[[^]]*\]$')

def lookup(pricing, model):
    if model in pricing: return pricing[model]
    base=SUFFIX.sub('',model)
    if base in pricing: return pricing[base]
    for key, price in pricing.items():
        if key.lower() in (model.lower(),base.lower()): return price
    return None

def process_cost(msg, pricing):
    if not msg.model_usage: return msg.total_cost_usd or 0
    total=0
    for model, usage in msg.model_usage.items():
        price=lookup(pricing,model)
        if price is None:
            total+=usage.get('costUSD',0) or 0
        else:
            total+=sum((usage.get(tokens,0) or 0)*getattr(price,field) for tokens,field in
                       (('inputTokens','input'),('outputTokens','output'),
                        ('cacheCreationInputTokens','cache_write'),('cacheReadInputTokens','cache_read')))/1e6
    return total
