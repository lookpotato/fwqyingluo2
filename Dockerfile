FROM python:3.11-slim

WORKDIR /app

RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120 fastapi uvicorn pydantic

COPY app.py /app/app.py

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]