import asyncio
import uuid
from gst_automation.core.settings import Settings
from gst_automation.db.session import Db
from gst_automation.portal.sessions import SessionManager

CLIENT_ID = uuid.UUID('b6cc7cd8-cbb7-53cc-a037-56e30d5501cf')

async def main() -> None:
    s = Settings.load()
    db = Db(s.database_url)
    async with db.session() as sess:
        st = await SessionManager(settings=s).load_latest_storage_state(sess, client_id=CLIENT_ID, profile='gst')
    await db.close()

    print('has_state', bool(st))
    if not isinstance(st, dict):
        print('state_type', type(st))
        return
    cookies = st.get('cookies') or []
    origins = st.get('origins') or []
    print('cookies', len(cookies))
    print('origins', len(origins))
    hosts = sorted({o.get('origin') for o in origins if isinstance(o, dict) and o.get('origin')})
    print('origin_hosts', hosts[:10])
    # Show a small sample of cookie domains/names (no values)
    sample = []
    for c in cookies[:20]:
        if isinstance(c, dict):
            sample.append({'name': c.get('name'), 'domain': c.get('domain'), 'path': c.get('path')})
    print('cookie_sample', sample)

if __name__ == '__main__':
    asyncio.run(main())
