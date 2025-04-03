import asyncio
import logging
from typing import Any, List
from slack_bolt.async_app import AsyncApp
from slack_sdk.oauth.installation_store.async_installation_store import AsyncInstallationStore
from slack_sdk.oauth.state_store.async_state_store import AsyncOAuthStateStore
from slack_bolt.oauth.async_oauth_settings import AsyncOAuthSettings
from markdown_to_mrkdwn import SlackMarkdownConverter
from potpie_service import Err, PotpieAPIClient
from store import AuthTokenStore, ConversationMappingStore

# Initialize logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def build_app(
    signing_secret: str,
    client_id: str,
    client_secret: str,
    potpie_client: PotpieAPIClient,
    token_store: AuthTokenStore,
    conversation_mapping_store: ConversationMappingStore,
    installation_store: AsyncInstallationStore,
    state_store: AsyncOAuthStateStore,
):
    logger.info("Building Slack application with provided credentials.")
    app = AsyncApp(
        signing_secret=signing_secret,
        oauth_settings=AsyncOAuthSettings(
            client_id=client_id,
            client_secret=client_secret,
            scopes=[
                "app_mentions:read", "commands", "im:history",
                "users:read", "im:read", "chat:write",
                "im:write", "reactions:read", "reactions:write",
            ],
            installation_store=installation_store,
            state_store=state_store,
            install_page_rendering_enabled=False,
        ),
        process_before_response=True,
    )

    @app.event("app_home_opened")
    async def handle_app_home(event, client):
        user_id = event["user"]
        logger.info(f"App home opened for user: {user_id}")
        home_view = {
            "type": "home",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Welcome to Potpie AI, <@{user_id}>! \u001f44f",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Explore our features or visit the About tab for more information.",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Learn More"},
                            "url": "https://docs.potpie.ai/introduction",
                        }
                    ],
                },
            ],
        }

        await client.views_publish(user_id=user_id, view=home_view)
        logger.debug(f"Home view published for user: {user_id}")

    @app.event("app_mention")
    async def mention(event, say, ack, client):
        await ack()
        team_id = event["team"]
        logger.debug(f"Mention received from team ID: {team_id}")

        potpie_token = await token_store.get_token(team_id)
        if potpie_token is None:
            await say("You haven't authenticated yet! Use `/authenticate` to start querying.")
            logger.warning("User attempted to mention before authentication.")
            return

        channel_id = event["channel"]
        thread_ts = event.get("thread_ts")
        if thread_ts is None:
            await say("Use `/potpie` command to start a conversation.")
            logger.info("User did not provide thread timestamp.")
            return

        conversation_id = await conversation_mapping_store.get_mapping(thread_ts)
        if conversation_id is None:
            await say("Use `/potpie` command to start a conversation.")
            logger.debug("No conversation mapping found for thread timestamp.")
            return

        await client.reactions_add(channel=channel_id, name="eyes", timestamp=event["ts"])
        asyncio.create_task(process_mention_query_task(potpie_token, conversation_id, event["text"], client, channel_id, thread_ts, event["ts"]))

    async def process_mention_query_task(potpie_token, conversation_id, query, client, channel_id, thread_id, message_id):
        try:
            logger.info(f"Processing query: {query} for conversation ID: {conversation_id}")
            processing_msg = await client.chat_postMessage(channel=channel_id, text="_Processing_ ...", thread_ts=thread_id)

            res = await potpie_client.send_message(potpie_token, conversation_id, query)
            if isinstance(res, Err):
                logger.error(f"Error in send_message: {res.message} {res.status_code}")
                raise Exception(Err)

            converter = SlackMarkdownConverter()
            await client.chat_postMessage(channel=channel_id, text=converter.convert(res), thread_ts=thread_id)
            await client.reactions_add(channel=channel_id, name="thumbsup", timestamp=message_id)
            await client.chat_delete(channel=channel_id, ts=processing_msg.data["ts"])
            logger.info("Successfully processed mention query.")

        except Exception as e:
            logger.error(f"Error in conversation flow: {e}", exc_info=True)
            await client.reactions_add(channel=channel_id, name="x", timestamp=message_id)
            await client.chat_postMessage(channel=channel_id, text="There was some error at our end! Please try again later", thread_ts=thread_id)

    @app.command("/authenticate")
    async def command_authenticate(ack, body, client):
        await ack()
        logger.debug("Authenticate command received.")
        channel_id = body["channel_id"]
        modal = {
            "type": "modal",
            "callback_id": "handle_authentication",
            "title": {"type": "plain_text", "text": "Authenticate"},
            "private_metadata": channel_id,
            "blocks": [{
                "type": "input",
                "block_id": "api_token_input",
                "label": {"type": "plain_text", "text": "Enter your API Token"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "api_token",
                    "placeholder": {"type": "plain_text", "text": "Your API Token"},
                },
            }],
            "submit": {"type": "plain_text", "text": "Submit"},
        }

        await client.views_open(trigger_id=body["trigger_id"], view=modal)
        logger.info(f"Opened authentication modal for channel: {channel_id}")

    # ... (rest of the code remains the same)