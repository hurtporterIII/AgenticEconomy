# Architecture

- Backend engine loop in `backend/core`
- Agent behaviors in `backend/agents`
- Economy actions in `backend/actions`
- Bank ledger in `backend/bank`
- Arc settlement adapter in `backend/tx/arc.py`
- API in `backend/api`
- Spawn API supports role selection with optional auto-generated IDs
- Global cap `MAX_TOTAL_AGENTS` limits total entities regardless of role
- Frontend Phaser app in `frontend`
- AI decision routing in `backend/services/oracle.py` (provider fallback)
