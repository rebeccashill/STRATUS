"""Run project tests while denying non-loopback Python network connections.

Uses only local Python test files. It never starts Wolfram, uploads data, or reads
service credentials. Provider tests inject their transports. Actual local kernel
checks are a separate, explicitly selected launcher step.
"""
import argparse
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def audit(event,args):
    if event in ('socket.connect','socket.sendto'):
        address=args[-1]
        host=address[0] if isinstance(address,tuple) else address
        if host not in ('127.0.0.1','::1','localhost'):raise PermissionError('Offline checks deny external network connections')
    if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost',None):raise PermissionError('Offline checks deny external DNS')
    if event=='subprocess.Popen':
        executable=args[0]
        command=args[1]
        allowed=(executable is not None and Path(str(executable)).resolve()==Path(sys.executable).resolve())
        if executable is None and isinstance(command,str):
            allowed=any(command.lower().startswith(prefix.lower()) for prefix in (sys.executable+' ','"'+sys.executable+'" '))
        if not allowed:raise PermissionError('Offline checks permit only this Python interpreter as a child tool')

def main():
    p=argparse.ArgumentParser();p.add_argument('--pattern',default='test_*.py');p.add_argument('--output',type=Path);args=p.parse_args()
    sys.addaudithook(audit)
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=args.pattern)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    from http_test_support import transport_counts
    record={'tests':result.testsRun,'passed':result.wasSuccessful(),'failures':len(result.failures),'errors':len(result.errors),'external_python_network':'denied by audit hook','scope':args.pattern,
            'http_test_transports':transport_counts(),'http_scope':'Real HTTP serialization, app handlers and response parsing; OS loopback sockets only where permitted'}
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record));return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
