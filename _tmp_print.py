import sys
print('out')
sys.stderr.write('err\\n')
raise SystemExit(2)
