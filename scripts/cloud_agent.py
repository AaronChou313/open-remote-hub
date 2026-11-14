"""Bind this Agent to an ORH Cloud account without handling its password."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import main, cloud_agent

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('action',choices=['bind','status','sync'])
parser.add_argument('--cloud-url',default='https://cloud.openremotehub.top')
args = parser.parse_args()
if args.action == 'bind':
    result = cloud_agent.begin_binding(args.cloud_url)
    print('绑定码:',result['user_code'])
    print('请登录自己的 Cloud 账号并确认绑定:',result['verification_url'])
    print('Agent 服务会自动完成绑定；绑定码十分钟内有效。')
elif args.action == 'sync':
    cloud_agent.synchronize()
    print(cloud_agent.status())
else:
    print(cloud_agent.status())
