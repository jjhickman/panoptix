FROM jjhickman/opencv
WORKDIR /camera

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .
CMD ["python3", "camera.py"]