FROM alpine:3.20
RUN apk add --no-cache chrony
COPY chrony.conf /etc/chrony/chrony.conf
EXPOSE 123/udp
CMD ["chronyd", "-d"]
