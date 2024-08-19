# setup
FROM  mirrors.tencent.com/lqgame-ai/public/ultron-independent-gpu-learner:ubuntu2204-py310-cu118 AS build-env

WORKDIR /app
COPY rtvi-backend/ /app/rtvi-backend
COPY rtvi-frontend/ /app/rtvi-frontend

WORKDIR /app/rtvi-backend

# If running on Ubuntu, Azure TTS requires some extra config
# https://learn.microsoft.com/en-us/azure/ai-services/speech-service/quickstarts/setup-platform?pivots=programming-language-python&tabs=linux%2Cubuntu%2Cdotnetcli%2Cdotnet%2Cjre%2Cmaven%2Cnodejs%2Cmac%2Cpypi

RUN wget -O - https://www.openssl.org/source/openssl-1.1.1w.tar.gz | tar zxf -
WORKDIR openssl-1.1.1w
RUN ./config --prefix=/usr/local
RUN make -j $(nproc)
RUN make install_sw install_ssldirs
RUN ldconfig -v
ENV SSL_CERT_DIR=/etc/ssl/certs

#ENV LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
RUN apt clean
RUN apt-get update
RUN apt-get -y install build-essential libssl-dev ca-certificates libasound2 wget libasound-dev portaudio19-dev libportaudio2 libportaudiocpp0

WORKDIR /app/rtvi-backend
RUN pip3 install --ignore-installed  -r requirements.txt
ENV PYTHONUNBUFFERED=1

WORKDIR /app/rtvi-frontend

# Installing Node
SHELL ["/bin/bash", "--login", "-i", "-c"]
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.0/install.sh | bash
RUN source /root/.bashrc && nvm install 20 && npm install && npm run build
SHELL ["/bin/bash", "--login", "-c"]

EXPOSE 7860 5173
# run
CMD sh start_frontend.sh && cd ../rtvi-backend/ && sh start_backend.sh
