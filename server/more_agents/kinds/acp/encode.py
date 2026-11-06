from ...store import MoreAgentsStore

def prompt(store, text, attachments, capabilities):
    return store.prompt(text, attachments, capabilities)
