FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ORH_CLOUD_DATA=/data ORH_CLOUD_WEB=/service/.runtime/portal-site
ARG PIP_INDEX_URL=https://pypi.org/simple
WORKDIR /service
COPY cloud/requirements.txt cloud/requirements.txt
RUN pip install --no-cache-dir -r cloud/requirements.txt
COPY cloud cloud
COPY portal portal
COPY scripts/build_portal.py scripts/build_portal.py
COPY static/icons.svg static/icons-LICENSE.txt static/
RUN python scripts/build_portal.py && useradd -u 10001 -m orh && mkdir /data && chown orh:orh /data
USER orh
EXPOSE 9090
CMD ["uvicorn", "cloud.main:app", "--host", "0.0.0.0", "--port", "9090", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
