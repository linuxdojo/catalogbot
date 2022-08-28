# CatalogBot

CatalogBot is a bidirectional link integration between the [CatalogIt](https://www.catalogit.app/) collection management system and a [Discourse](https://www.discourse.org/) forum server.

CatalogBot allows CatalogIt users to create "Discuss this item on our forum" weblinks that, when clicked, will redirect the user to a discussion topic for the item in your Discourse forum, creating the topic if it does not already exist.

## Attributions/License

This integration was created for the [Autralian Computer Museum Society](https://acms.org.au) and is released under the GPLv3.

## Installation

The integration can be run in a Pyton 3.10 virtualenv, or via Docker. Refer to the `.environ.example` file if you want to run this integration locally.

The Docker image is available at https://hub.docker.com/r/linuxdojo/catalogbot

## Usage via Docker

Create an Discourse API user with full global permissions and specify the below env vars to start the integration:

```
docker run -it \
-e CIT_ACCOUNT_ID=YOUR_ACCOUNT_ID \
-e DISCOURSE_API_URL="https://YOUR_DISCOURSE_SITE_DOMAIN_NAME" \
-e DISCOURSE_API_USERNAME="YOUR_DISCOURSE_API_USER" \
-e DISCOURSE_API_KEY="YOUR_DISCOURSE_API_KEY" \
-e DISCOURSE_CATEGORY="Our CatalogIt Collection" \
-e INT_BASE_URL="YOUR_INTEGRATION_URL" \
-e INT_BIND_HOST="0.0.0.0" \
-e INT_BIND_PORT=80 \
-p  80:80 \
linuxdojo/catalogbot
```
Where:

* `CIT_ACCOUNT_ID` is your CatalogIt account ID.
* `DISCOURSE_CATEGORY` is the Category under which new Discourse forum topics are auto-created for CatalogIt Entries (this Category will be auto-created if it doesn't exist)
* `INT_BASE_URL` is the HTTP URL that resolves to the host and port on which this integration is running, eg `http://my.server` or `http://my.server:8080`. Note that if you use a port other that 80, then you must specify the same port in the left most integer value of the `-p`, option, eg `-p 8080:80`

In CatalogIt, create Weblinks for your Entries with name `Discuss this item on our forum`, and value `INT_BASE_URL/UUID` where `UUID` is a randomly generated version 4 UUID (you can generaete these [here](https://www.uuidgenerator.net/), or from within in a spreadsheet app, etc).

### User Experience

Clicking the new Weblink in CatalogIt will simply forward the user to the Discourse topic discussing the item.

Under the hood, the the integration will create a new topic for the entry in Discourse if one does not currently exist, and redirect the user there. The topic will contain the title of the entry, an image if present in the entry, and a link back to the CatalogIt entry itself.
