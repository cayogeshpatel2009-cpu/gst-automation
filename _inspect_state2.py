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

    origins = st.get('origins') or [] if isinstance(st, dict) else []
    if origins:
        o = origins[0]
        print('origin_keys', sorted(o.keys()))
        ls = o.get('localStorage') or []
        ss = o.get('sessionStorage') or []
        print('localStorage_len', len(ls))
        print('sessionStorage_len', len(ss))
        print('localStorage_sample_keys', [x.get('name') for x in ls[:10] if isinstance(x, dict)])

if __name__ == '__main__':
    asyncio.run(main())
