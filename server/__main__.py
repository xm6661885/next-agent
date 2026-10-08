"""Run the backend or change its password."""
import argparse
import getpass
import os
import bcrypt
import uvicorn
from .paths import DataDir
from .config import ConfigStore

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',nargs='?',choices=['set-password'])
    args=parser.parse_args()
    config=ConfigStore(DataDir())
    if args.command=='set-password':
        first=getpass.getpass('New password: ')
        second=getpass.getpass('Repeat password: ')
        if first!=second or not first:
            raise SystemExit('Passwords do not match or are empty')
        config.doc['server']['password_hash']=bcrypt.hashpw(first.encode(),bcrypt.gensalt()).decode()
        config.save()
    else:
        uvicorn.run('server.app:create_app',factory=True,host=config.config.server.host,
                    port=int(os.getenv('NEXT_AGENT_PORT',config.config.server.port)),
                    proxy_headers=True,forwarded_allow_ips='*')
if __name__=='__main__': main()
