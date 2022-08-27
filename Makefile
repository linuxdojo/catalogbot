.SILENT:

help: # Show this help
	@echo Make targets:
	@egrep -h ":\s+# " $(MAKEFILE_LIST) | \
	  sed -e 's/# //; s/^/    /' | \
	  column -s: -t

testcert: # Make a self-signed test cert
	openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -sha256 -days 365 -nodes -subj "/C=US/ST=Oregon/L=Portland/O=Company Name/OU=Org/CN=localhost"
	cat cert.pem key.pem > localhost.pem
	rm -f key.pem cert.pem
