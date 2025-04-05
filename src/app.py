import asyncio
import logging
from typing import Any, List
from slack_bolt.async_app import AsyncApp
from slack_sdk.oauth.installation_store.async_installation_store import (
    AsyncInstallationStore,
)
from slack_sdk.oauth.state_store.async_state_store import AsyncOAuthStateStore
from slack_bolt.oauth.async_oauth_settings import AsyncOAuthSettings
from markdown_to_mrkdwn import SlackMarkdownConverter
from potpie_service import Err, PotpieAPIClient
from store import (
    AuthTokenStore,
    ConversationMappingStore,
)


# Initialize logging with improved format
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
    # Log application initialization
    logger.info("Building Slack application with provided credentials")
    
    # Initialize the installation store
    app = AsyncApp(
        signing_secret=signing_secret,
        oauth_settings=AsyncOAuthSettings(
            client_id=client_id,
            client_secret=client_secret,
            scopes=[
                "app_mentions:read",
                "commands",
                "im:history",
                "users:read",
                "im:read",
                "chat:write",
                "im:write",
                "reactions:read",
                "reactions:write",
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

        # Define the content for the Home tab using Block Kit
        home_view = {
            "type": "home",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Welcome to Potpie AI, <@{user_id}>! 🎉",
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

        # Publish the view to the user's Home tab
        await client.views_publish(user_id=user_id, view=home_view)
        logger.debug(f"Home view published successfully for user: {user_id}")

    @app.event("app_mention")
    async def mention(event, say, ack, client):
        await ack()
        team_id = event["team"]
        logger.debug(f"Mention event received from team: {team_id}")

        # Auth Guard
        potpie_token = await token_store.get_token(team_id)
        if potpie_token is None:
            logger.warning(f"Authentication missing for team: {team_id}")
            await say(
                "You haven't authenticated yet! Set your _token_ using `/authenticate` to start querying."
            )
            return

        channel_id = event["channel"]
        thread_ts = event.get("thread_ts")
        
        if thread_ts is None:
            logger.info(f"Mention without thread context in channel: {channel_id}")
            await say("Use `/potpie` command to start a conversation.")
            return

        conversation_id = await conversation_mapping_store.get_mapping(thread_ts)
        if conversation_id is None:
            logger.info(f"No conversation mapping found for thread: {thread_ts}")
            await say("Use `/potpie` command to start a conversation.")
            return

        logger.info(f"Processing mention in channel: {channel_id}, thread: {thread_ts}")
        await client.reactions_add(
            channel=channel_id,
            name="eyes",
            timestamp=event["ts"],
        )
        
        asyncio.create_task(
            process_mention_query_task(
                potpie_token,
                conversation_id,
                event["text"],
                client,
                channel_id,
                thread_ts,
                event["ts"],
            )
        )
        return

    async def process_mention_query_task(
        potpie_token, conversation_id, query, client, channel_id, thread_id, message_id
    ):
        try:
            logger.debug(f"Processing query: {query} for conversation ID: {conversation_id}")
            processing_msg = await client.chat_postMessage(
                channel=channel_id,
                text="_Processing_ ...",
                thread_ts=thread_id,
            )

            logger.debug(f"Sending message to Potpie API for conversation: {conversation_id}")
            res = await potpie_client.send_message(potpie_token, conversation_id, query)
            if isinstance(res, Err):
                logger.error(f"Error in send_message: {res.message} {res.status_code}")
                raise Exception(Err)

            converter = SlackMarkdownConverter()
            await client.chat_postMessage(
                channel=channel_id,
                text=converter.convert(res),
                thread_ts=thread_id,
            )
            
            await client.reactions_add(
                channel=channel_id,
                name="thumbsup",
                timestamp=message_id,
            )

            await client.chat_delete(channel=channel_id, ts=processing_msg.data["ts"])
            logger.info(f"Successfully processed mention query for conversation: {conversation_id}")

        except Exception as e:
            logger.error(f"Error in conversation flow: {e}", exc_info=True)
            await client.reactions_add(
                channel=channel_id,
                name="x",
                timestamp=message_id,
            )
            await client.chat_postMessage(
                channel=channel_id,
                text="There was some error at our end! Please try again later.",
                thread_ts=thread_id,
            )

    @app.command("/authenticate")
    async def command_authenticate(ack, body, client):
        await ack()  # Acknowledge the command
        channel_id = body["channel_id"]
        logger.info(f"Authentication command received from channel: {channel_id}")

        # Define the modal view with an input field for API token
        modal = {
            "type": "modal",
            "callback_id": "handle_authentication",
            "title": {"type": "plain_text", "text": "Authenticate"},
            "private_metadata": channel_id,
            "blocks": [
                {
                    "type": "input",
                    "block_id": "api_token_input",
                    "label": {
                        "type": "plain_text",
                        "text": "Enter your API Token",
                    },
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "api_token",
                        "placeholder": {"type": "plain_text", "text": "Your API Token"},
                    },
                }
            ],
            "submit": {"type": "plain_text", "text": "Submit"},
        }

        # Open the modal
        await client.views_open(trigger_id=body["trigger_id"], view=modal)
        logger.debug(f"Authentication modal opened for channel: {channel_id}")

    @app.view("handle_authentication")
    async def handle_authentication(ack, body, client):
        await ack()  # Acknowledge the command
        logger.debug("Handling authentication view submission")

        try:
            user_id = body["team"]["id"]
            potpie_token = body["view"]["state"]["values"]["api_token_input"][
                "api_token"
            ]["value"]

            logger.info(f"Setting token for user: {user_id}")
            await token_store.set_token(user_id, potpie_token)

            channel_id = body["view"][
                "private_metadata"
            ]  # This was passed when creating modal

            # Send the direct message
            await client.chat_postMessage(
                channel=channel_id,
                text="*You have been Authenticated Successfully!*\n\n• Use `/potpie` command to start a conversation\n",
            )
            logger.info(f"Authentication successful for user: {user_id}")
        except Exception as e:
            logger.error(f"Error during authentication: {e}", exc_info=True)

    @app.command("/potpie")
    async def start_conversation(ack, body, client):
        await ack()
        # Call views_open with the built-in client
        logger.info("Potpie command received")
        team_id = body["team_id"]

        # Auth Guard
        potpie_token = await token_store.get_token(team_id)
        if potpie_token is None:
            logger.warning(f"Authentication missing for team: {team_id}")
            await ack(
                "You haven't authenticated yet! Set your _token_ using `/authenticate` to start querying."
            )
            return

        try:
            logger.debug("Fetching projects from Potpie API")
            res = await potpie_client.fetch_projects(potpie_token)
            if isinstance(res, Err):
                logger.error(
                    f"Error fetching projects: {res.message} {res.status_code}"
                )
                raise Exception("Error retrieving projects")

            ready_projects = [project for project in res if project.status == "ready"]
            logger.debug(f"Found {len(ready_projects)} ready projects")

            logger.debug("Fetching agents from Potpie API")
            res = await potpie_client.fetch_agents(potpie_token)
            if isinstance(res, Err):
                logger.error(
                    f"Error fetching agents: {res.message} {res.status_code}"
                )
                raise Exception("Error retrieving agents")

            available_agents = res
            logger.debug(f"Found {len(available_agents)} available agents")

        except Exception as e:
            logger.error(f"Error retrieving data: {e}", exc_info=True)
            await ack("Error retrieving data! Please try again later.")
            return

        if len(ready_projects) == 0:
            logger.info("No ready projects found for user")
            await ack(
                "You don't have any ready projects, please parse your repo before starting conversation."
            )
            return

        if len(available_agents) == 0:
            logger.warning("No agents available for user")
            await ack("No agents available!")  # Just a sanity check
            return

        project_options = [
            {"text": {"type": "plain_text", "text": project.name}, "value": project.id}
            for project in ready_projects
        ]

        available_agents = [
            {"text": {"type": "plain_text", "text": agent.name}, "value": agent.id}
            for agent in available_agents
        ]

        channel_id = body["channel_id"]
        logger.info(f"Opening conversation modal for channel: {channel_id}")

        await client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "PotpieAI", "emoji": True},
                "submit": {"type": "plain_text", "text": "Submit", "emoji": True},
                "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
                "callback_id": "start-conversation-modal",
                "private_metadata": channel_id,
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Please select the repo and agent*:",
                        },
                    },
                    {"type": "divider"},
                    {
                        "type": "input",
                        "block_id": "select-repo-input",
                        "label": {"type": "plain_text", "text": "Choose a repository"},
                        "element": {
                            "type": "static_select",
                            "action_id": "select-repo-action",
                            "options": project_options,
                            "initial_option": project_options[0],
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "select-agent-input",
                        "label": {"type": "plain_text", "text": "Choose an agent"},
                        "element": {
                            "type": "static_select",
                            "action_id": "select-agent-action",
                            "options": available_agents,
                            "initial_option": available_agents[0],
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "user_query_block",
                        "label": {"type": "plain_text", "text": "Ask the AI Agent"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "user_query_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "Type your question here...",
                            },
                            "multiline": True,
                        },
                    },
                ],
            },
        )

    @app.view("start-conversation-modal")
    async def handle_submission(ack, body, client):
        await ack()
        logger.debug("Processing conversation modal submission")
        try:
            team_id = body["user"]["team_id"]
            # Auth Guard
            potpie_token = await token_store.get_token(team_id)
            if potpie_token is None:
                logger.warning(f"Authentication missing for team: {team_id}")
                await ack(
                    "You haven't authenticated yet! Set your _token_ using `/authenticate` to start querying."
                )
                return

            project_id = body["view"]["state"]["values"]["select-repo-input"][
                "select-repo-action"
            ]["selected_option"]["value"]
            project_list: List[Any] = body["view"]["blocks"][2]["element"]["options"]
            project_name = ""
            for project in project_list:
                if project["value"] == project_id:
                    project_name = project["text"]["text"]
                    break

            agent_id = body["view"]["state"]["values"]["select-agent-input"][
                "select-agent-action"
            ]["selected_option"]["value"]
            agents_list: List[Any] = body["view"]["blocks"][3]["element"]["options"]
            agent_name = ""
            for agent in agents_list:
                if agent["value"] == agent_id:
                    agent_name = agent["text"]["text"]
                    break

            query = body["view"]["state"]["values"]["user_query_block"][
                "user_query_input"
            ]["value"]

            channel_id = body["view"][
                "private_metadata"
            ]  # This was passed when creating modal
            
            logger.info(f"Creating conversation for project: {project_id}, agent: {agent_id}")
            conv = await potpie_client.create_conversation(
                potpie_token, project_id, agent_id
            )

            if isinstance(conv, Err):
                logger.error(f"Error creating conversation: {conv.message} {conv.status_code}")
                raise Exception(Err)

            # Send the direct message
            logger.debug(f"Posting initial message to channel: {channel_id}")
            res = await client.chat_postMessage(
                channel=channel_id,
                text=f"📁 Project: *{project_name}* \n🤖 Agent: *{agent_name}*  \n\n> _"{query}"_  🔍",
            )

            await conversation_mapping_store.set_mapping(res.data["ts"], conv)
            logger.info(f"Conversation mapping created: {res.data['ts']} -> {conv}")

            asyncio.create_task(
                process_query_task(
                    potpie_token,
                    conv,
                    query,
                    channel_id,
                    res.data["ts"],
                    body["user"]["id"],
                    client,
                )
            )

        except Exception as e:
            logger.error(f"Error setting conversation: {e}", exc_info=True)
            await client.chat_postEphemeral(
                channel=body["view"]["private_metadata"],
                user=body["user"]["id"],
                text="Failed to create conversation. Please try again later.",
            )

    async def process_query_task(
        potpie_token, conversation_id, query, channel_id, thread_id, user_id, client
    ):
        try:
            logger.debug(f"Processing query task for conversation: {conversation_id}")
            processing_msg = await client.chat_postMessage(
                channel=channel_id,
                text="_Processing_ ...",
                thread_ts=thread_id,
                user_id=user_id,
            )

            await client.reactions_add(
                channel=channel_id,
                name="eyes",
                timestamp=thread_id,
            )

            logger.debug(f"Sending initial message to Potpie API for conversation: {conversation_id}")
            ans = await potpie_client.send_message(potpie_token, conversation_id, query)
            if isinstance(ans, Err):
                logger.error(f"Error sending message: {ans.message} {ans.status_code}")
                raise Exception(Err)

            converter = SlackMarkdownConverter()
            await client.chat_postMessage(
                channel=channel_id,
                text=converter.convert(ans)
                + "\nYou can *@mention* me to continue the conversation",
                thread_ts=thread_id,
            )

            await client.reactions_add(
                channel=channel_id,
                name="thumbsup",
                timestamp=thread_id,
            )

            await client.chat_delete(channel=channel_id, ts=processing_msg.data["ts"])
            logger.info(f"Successfully processed query for conversation: {conversation_id}")

        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_id,
                text="Error processing your request. Please try again later.",
            )

    return app