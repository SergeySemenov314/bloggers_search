FROM python:3.12-slim

WORKDIR /app

# Ставим зависимости отдельным слоем (кэшируется между сборками)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Каталог для кэша Apify и журнала показанных — сюда монтируется том,
# чтобы платный кэш переживал пересборку контейнера.
ENV DATA_DIR=/app/data
RUN mkdir -p /app/data

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
