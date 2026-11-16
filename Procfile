console: streamlit run src/bastion/console/app.py --server.port ${PORT:-8501} --server.address ${BASTION_BIND:-127.0.0.1} --server.headless true --browser.gatherUsageStats false
api: uvicorn bastion.api.main:app --factory --host ${BASTION_API_BIND:-127.0.0.1} --port 8000
