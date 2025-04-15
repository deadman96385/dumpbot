import logging
from typing import List, Tuple

import httpx

from dumpyarabot import schemas
from dumpyarabot.config import settings

# Use the logger defined in __init__
logger = logging.getLogger("rich")


def parse_options(options_str: str) -> Tuple[bool, bool, bool, bool]:
    """Parses the options string from commands."""
    options = "".join(options_str.split())
    use_alt_dumper = 'a' in options
    force = 'f' in options
    add_blacklist = 'b' in options
    use_privdump = 'p' in options
    return use_alt_dumper, force, add_blacklist, use_privdump

async def get_jenkins_builds(job_name: str) -> List[schemas.JenkinsBuild]:
    """Fetch all builds from Jenkins for a specific job."""
    logger.info(f"Fetching builds for job: {job_name}")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{settings.JENKINS_URL}/job/{job_name}/api/json",
                params={
                    "tree": "allBuilds[number,result,actions[parameters[name,value]]]"
                },
                auth=(settings.JENKINS_USER_NAME, settings.JENKINS_USER_TOKEN),
                timeout=30.0,
            )
            response.raise_for_status()
            builds = [
                schemas.JenkinsBuild(**build) for build in response.json()["allBuilds"]
            ]
            logger.info(f"Successfully fetched {len(builds)} builds for {job_name}")
            return builds
        except Exception as e:
            logger.error(f"Failed to fetch builds for {job_name}: {e}", exc_info=False) # Log less detail
            raise


def _is_matching_build(
    build: schemas.JenkinsBuild, args: schemas.DumpArguments
) -> bool:
    """Check if a build matches the given arguments."""
    for action in build.actions:
        if "parameters" in action:
            params = {param["name"]: param["value"] for param in action["parameters"]}
            try:
                # Basic comparison, assuming Jenkins params might be strings
                jenkins_alt = str(params.get("USE_ALT_DUMPER", 'false')).lower() == str(args.use_alt_dumper).lower()
                jenkins_blacklist = str(params.get("ADD_BLACKLIST", 'false')).lower() == str(args.add_blacklist).lower()
                jenkins_privdump = str(params.get("USE_PRIVDUMP", 'false')).lower() == str(args.use_privdump).lower()
            except Exception:
                continue # Skip if parameters are malformed

            if matches := (
                params.get("URL") == args.url.unicode_string()
                and jenkins_alt
                and jenkins_blacklist
                and jenkins_privdump
            ):
                return matches
    return False


def _get_build_status(build: schemas.JenkinsBuild) -> Tuple[bool, str]:
    """Get the status of a build (running/succeeded or other)."""
    job_name = "dumpyara" # Assume default unless privdump detected
    try:
        for action in build.actions:
            if "parameters" in action:
                params = {param["name"]: param["value"] for param in action["parameters"]}
                if str(params.get("USE_PRIVDUMP", 'false')).lower() == 'true':
                    job_name = "privdump"
                    break
    except Exception: pass # Ignore errors checking params

    if build.result is None:
        return (True, f"Build #{build.number} is currently in progress for this URL/settings in job '{job_name}'.")
    elif build.result == "SUCCESS":
        return (True, f"Build #{build.number} has already successfully completed for this URL/settings in job '{job_name}'.")
    else:
        return (False, f"Build #{build.number} exists for this URL/settings in job '{job_name}', but result was {build.result}.")


async def check_existing_build(args: schemas.DumpArguments) -> Tuple[bool, str]:
    """Check if a build with the given parameters already exists and is running or succeeded."""
    job_name = "privdump" if args.use_privdump else "dumpyara"
    logger.info(f"Checking existing builds for {job_name} with URL {args.url}")

    try:
        builds = await get_jenkins_builds(job_name)
    except Exception:
        logger.warning(f"Could not retrieve builds for {job_name}. Assuming no existing blocking build.")
        return False, "Could not check for existing builds."

    for build in builds:
        if _is_matching_build(build, args):
            exists_and_ok, message = _get_build_status(build)
            if exists_and_ok:
                logger.info(f"Found matching active/successful build - Status: {message}")
                return True, message # Blocks new build

    return False, f"No matching running/successful build found."


async def call_jenkins(args: schemas.DumpArguments) -> str:
    """Call Jenkins to start a new build."""
    job_name = "privdump" if args.use_privdump else "dumpyara"
    logger.info(f"Starting new {job_name} build for URL: {args.url}")
    logger.debug(f"Build parameters: {args.model_dump_json(exclude_none=True)}")

    params = {
        "URL": args.url.unicode_string(),
        "USE_ALT_DUMPER": str(args.use_alt_dumper).lower(),
        "ADD_BLACKLIST": str(args.add_blacklist).lower(),
        "USE_PRIVDUMP": str(args.use_privdump).lower(),
        "INITIAL_MESSAGE_ID": str(args.initial_message_id) if args.initial_message_id is not None else "",
    }
    params = {k: v for k, v in params.items() if v != ""}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{settings.JENKINS_URL}/job/{job_name}/buildWithParameters",
                params=params,
                auth=(settings.JENKINS_USER_NAME, settings.JENKINS_USER_TOKEN),
                timeout=60.0
            )
            response.raise_for_status()
            queue_id_str = ""
            queue_url = response.headers.get('Location')
            if queue_url:
                 try: queue_id_str = f" (Queue ID: {queue_url.strip('/').split('/')[-1]})"
                 except Exception: pass
            logger.info(f"Successfully triggered {job_name} build{queue_id_str}.")
            return f"{job_name.capitalize()} job triggered successfully{queue_id_str}."
        except httpx.HTTPStatusError as e:
             logger.error(f"Failed to trigger {job_name} build. Status: {e.response.status_code}. Response: {e.response.text}")
             return f"Error triggering Jenkins job: Status {e.response.status_code}"
        except Exception as e:
            logger.error(f"Failed to trigger {job_name} build: {e}", exc_info=False) # Less detail
            return f"An unexpected error occurred triggering the {job_name} job."


async def cancel_jenkins_job(job_id: str, use_privdump: bool = False) -> str:
    """Cancel a Jenkins job by build number or queue ID."""
    job_name = "privdump" if use_privdump else "dumpyara"
    logger.info(f"Attempting to cancel {job_name} job/queue item {job_id}")

    async with httpx.AsyncClient() as client:
        # 1. Try stopping build
        try:
            stop_url = f"{settings.JENKINS_URL}/job/{job_name}/{job_id}/stop"
            response = await client.post(stop_url, auth=(settings.JENKINS_USER_NAME, settings.JENKINS_USER_TOKEN), follow_redirects=True, timeout=30.0)
            if response.status_code in [200, 302]:
                 logger.info(f"Stop request sent for build #{job_id} in {job_name}.")
                 return f"Stop request sent for build #{job_id} in {job_name}."
            elif response.status_code == 404:
                 logger.info(f"Build #{job_id} not found or completed in {job_name}. Checking queue...")
            else:
                 logger.warning(f"Unexpected status {response.status_code} stopping build #{job_id}. Checking queue.")
        except Exception as e:
             logger.error(f"Error stopping build #{job_id}: {e}. Checking queue.")

        # 2. Try cancelling queue item
        try:
            queue_item_id = str(job_id)
            cancel_url = f"{settings.JENKINS_URL}/queue/cancelItem"
            response = await client.post(cancel_url, params={"id": queue_item_id}, auth=(settings.JENKINS_USER_NAME, settings.JENKINS_USER_TOKEN), follow_redirects=True, timeout=30.0)
            if response.status_code in [204, 302]:
                logger.info(f"Successfully cancelled queue item {queue_item_id}.")
                return f"Job/Queue item {queue_item_id} has been cancelled."
            elif response.status_code == 404:
                 logger.warning(f"Queue item {queue_item_id} not found.")
                 return f"Failed to cancel job/queue item {queue_item_id}. Not found running or in queue."
            else:
                logger.warning(f"Failed to cancel queue item {queue_item_id}. Status: {response.status_code}")
                return f"Failed to cancel job/queue item {queue_item_id}. Status: {response.status_code}."
        except Exception as e:
            logger.error(f"Error cancelling queue item {job_id}: {e}")
            return f"An error occurred cancelling queue item {job_id}."