FROM alpine:3.22
RUN apk add --no-cache openssh-server && adduser -D tester && echo 'tester:orh-isolated-fixture-password' | chpasswd && ssh-keygen -A
RUN printf 'PasswordAuthentication yes\nPubkeyAuthentication yes\nPermitRootLogin no\nUsePAM no\nLogLevel VERBOSE\n' > /etc/ssh/sshd_config
EXPOSE 22
CMD ["/usr/sbin/sshd", "-D", "-e"]
