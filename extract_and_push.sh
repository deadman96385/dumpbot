#!/usr/bin/env bash

# Redis messaging configuration (replaces API_KEY requirement)
[[ -z ${REDIS_URL} ]] && REDIS_URL="redis://localhost:6379/0"
[[ -z ${REDIS_KEY_PREFIX} ]] && REDIS_KEY_PREFIX="dumpyarabot:"
[[ -z ${PYTHON_CMD} ]] && PYTHON_CMD="python3"

[[ -z ${GITLAB_SERVER} ]] && GITLAB_SERVER="dumps.tadiphone.dev"
[[ -z ${PUSH_HOST} ]] && PUSH_HOST="dumps"
[[ -z $ORG ]] && ORG="dumps"

CHAT_ID="-1001412293127"

[[ -z ${INITIAL_MESSAGE_ID} ]] && START_MESSAGE_ID="" || START_MESSAGE_ID="${INITIAL_MESSAGE_ID}"
[[ -z ${INITIAL_CHAT_ID} ]] && REPLY_CHAT_ID="" || REPLY_CHAT_ID="${INITIAL_CHAT_ID}"

# Redis message publisher function
publish_to_redis() {
    local message_type="$1"
    local priority="$2"
    local chat_id="$3"
    local text="$4"
    local reply_to_message_id="$5"
    local reply_to_chat_id="$6"
    local keyboard="$7"

    # Use Python to publish to Redis
    $PYTHON_CMD << EOF
import json
import sys
import uuid
import redis
from datetime import datetime

try:
    # Connect to Redis
    redis_client = redis.from_url("$REDIS_URL", decode_responses=True)

    # Create message data
    message_data = {
        "message_id": str(uuid.uuid4()),
        "type": "$message_type",
        "priority": "$priority",
        "chat_id": int("$chat_id"),
        "text": """$text""",
        "parse_mode": "Markdown",
        "reply_to_message_id": int("$reply_to_message_id") if "$reply_to_message_id" else None,
        "reply_parameters": None,
        "edit_message_id": None,
        "delete_after": None,
        "keyboard": $keyboard if "$keyboard" != "null" else None,
        "disable_web_page_preview": True,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "scheduled_for": None,
        "context": {
            "jenkins_script": True,
            "build_id": "$BUILD_ID",
            "job_name": "$JOB_NAME",
            "build_url": "$BUILD_URL"
        }
    }

    # Handle cross-chat replies
    if "$reply_to_chat_id" and "$reply_to_chat_id" != "$chat_id":
        message_data["reply_parameters"] = {
            "message_id": int("$reply_to_message_id"),
            "chat_id": int("$reply_to_chat_id")
        }
        message_data["reply_to_message_id"] = None
        message_data["type"] = "cross_chat"
        message_data["priority"] = "high"

    # Determine queue and publish
    queue_key = "${REDIS_KEY_PREFIX}msg_queue:" + message_data["priority"]
    redis_client.lpush(queue_key, json.dumps(message_data))
    print(f"[$(date '+%Y-%m-%d %H:%M:%S')] Published {message_data['type']} message to {message_data['priority']} queue")

except Exception as e:
    print(f"Error publishing to Redis: {e}", file=sys.stderr)
    sys.exit(1)
EOF
}

# usage: normal - sendTG normal "message to send"
#        reply  - sendTG reply message_id "reply to send"
#        edit   - sendTG edit message_id "new message" ( new message must be different )
# Now publishes to Redis instead of direct Telegram API
sendTG() {
    local mode="${1:?Error: Missing mode}" && shift

    case "${mode}" in
        normal)
            local text="$*"
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] sendTG normal: ${text:0:100}..."
            publish_to_redis "status_update" "normal" "$CHAT_ID" "$text" "" "" "null"
            ;;
        reply)
            local message_id="${1:?Error: Missing message id for reply.}" && shift
            local text="$*"
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] sendTG reply: ${text:0:100}..."
            publish_to_redis "status_update" "high" "$CHAT_ID" "$text" "$message_id" "$REPLY_CHAT_ID" "null"
            ;;
        edit)
            local message_id="${1:?Error: Missing message id for edit.}" && shift
            local text="$*"
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] sendTG edit: ${text:0:100}..."
            # For edit mode, send as new message since we don't track message IDs from queue
            publish_to_redis "status_update" "normal" "$CHAT_ID" "$text" "" "" "null"
            ;;
        *)
            echo "Error: Invalid sendTG mode '$mode'. Use 'normal', 'reply', or 'edit'." >&2
            return 1
            ;;
    esac
}

# Enhanced sendTG function that includes cancel button for Jenkins jobs
# usage: cancel_reply - sendTG_with_cancel cancel_reply message_id "reply to send"
# Uses global vars BUILD_ID, JOB_NAME (no longer needs API_KEY)
sendTG_with_cancel() {
    local mode="${1:?Error: Missing mode}" && shift

    if [[ ${mode} =~ cancel_reply ]]; then
        local message_id="${1:?Error: Missing message id for reply.}" && shift
        local text="$*"

        # Create cancel button inline keyboard
        local job_name="${JOB_NAME,,}"  # Convert to lowercase
        [[ "${job_name}" == *"privdump"* ]] && job_name="privdump" || job_name="dumpyara"
        local cancel_keyboard="{\"inline_keyboard\":[[{\"text\":\"🛑 Cancel ${job_name^} Job\",\"callback_data\":\"jenkins_cancel_${job_name}:${BUILD_ID}\"}]]}"

        echo "[$(date '+%Y-%m-%d %H:%M:%S')] sendTG_with_cancel: ${text:0:100}..."
        publish_to_redis "status_update" "high" "$CHAT_ID" "$text" "$message_id" "$REPLY_CHAT_ID" "$cancel_keyboard"
    else
        echo "Error: Invalid sendTG_with_cancel mode '$mode'. Use 'cancel_reply'." >&2
        return 1
    fi
}

# usage: temporary - To just edit the last message sent but the new content will be overwritten when this function is used again
#                    sendTG_edit_wrapper temporary "${MESSAGE_ID}" new message
#        permanent - To edit the last message sent but also store it permanently, new content will be appended when this function is used again
#                    sendTG_edit_wrapper permanent "${MESSAGE_ID}" new message
# Uses global var MESSAGE for all message contents
sendTG_edit_wrapper() {
    local mode="${1:?Error: Missing mode}" && shift
    local message_id="${1:?Error: Missing message id variable}" && shift
    local text="$*"

    case "${mode}" in
        temporary)
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] sendTG_edit_wrapper temporary: ${text:0:100}..."
            publish_to_redis "status_update" "normal" "$CHAT_ID" "$text" "" "" "null"
            ;;
        permanent)
            MESSAGE="$text"
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] sendTG_edit_wrapper permanent: ${text:0:100}..."
            publish_to_redis "status_update" "normal" "$CHAT_ID" "$MESSAGE" "" "" "null"
            ;;
        *)
            echo "Error: Invalid sendTG_edit_wrapper mode '$mode'. Use 'temporary' or 'permanent'." >&2
            return 1
            ;;
    esac
}

# Additional convenience functions for better message categorization
sendTG_error() {
    local text="$*"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] sendTG_error: ${text:0:100}..."
    publish_to_redis "error" "urgent" "$CHAT_ID" "$text" "$START_MESSAGE_ID" "$REPLY_CHAT_ID" "null"
}

sendTG_success() {
    local text="$*"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] sendTG_success: ${text:0:100}..."
    publish_to_redis "notification" "high" "$CHAT_ID" "$text" "$START_MESSAGE_ID" "$REPLY_CHAT_ID" "null"
}

# Log Redis messaging system status
echo "=== Redis Telegram Messaging System Active ==="
echo "Redis URL: $REDIS_URL"
echo "Redis Key Prefix: $REDIS_KEY_PREFIX"
echo "Chat ID: $CHAT_ID"
echo "Initial Message ID: $START_MESSAGE_ID"
echo "Reply Chat ID: $REPLY_CHAT_ID"
echo "Build ID: $BUILD_ID"
echo "Job Name: $JOB_NAME"
echo "=============================================="



# Analyze Jenkins console log with Gemini AI
analyze_jenkins_log() {
    # Check if GEMINI_API_KEY is set and if we have access to Python
    if [[ -z "${GEMINI_API_KEY}" ]] || ! command -v python3 &> /dev/null; then
        echo "[INFO] Gemini AI log analysis not available (missing API key or Python)"
        return 1
    fi

    echo "[INFO] Fetching Jenkins console log for analysis..."

    # Fetch console log from Jenkins (use authentication if available)
    local console_log
    if [[ -n "${JENKINS_USER}" ]] && [[ -n "${JENKINS_TOKEN}" ]]; then
        console_log=$(curl -s -u "${JENKINS_USER}:${JENKINS_TOKEN}" "${BUILD_URL}consoleText")
    else
        console_log=$(curl -s "${BUILD_URL}consoleText")
    fi

    # Check if we got a valid log
    if [[ -z "${console_log}" ]] || [[ ${#console_log} -lt 100 ]]; then
        echo "[ERROR] Failed to fetch console log or log too short"
        return 1
    fi

    echo "[INFO] Analyzing console log with Gemini AI..."

    # Create temporary Python script for analysis
    local analysis_script="/tmp/analyze_jenkins_log_$$.py"
    cat > "${analysis_script}" << 'EOF'
import sys
import os
import asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dumpyarabot.gemini_analyzer import analyzer

async def main():
    console_log = sys.stdin.read()
    build_info = {
        "job_name": os.environ.get("JOB_NAME", ""),
        "build_number": os.environ.get("BUILD_ID", ""),
        "build_url": os.environ.get("BUILD_URL", ""),
        "url": os.environ.get("URL", "")
    }

    analysis = await analyzer.analyze_jenkins_log(console_log, build_info)
    if analysis:
        formatted = analyzer.format_analysis_for_telegram(analysis, build_info.get("build_url", ""))
        print(formatted)
    else:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
EOF

    # Run analysis
    local analysis_result
    analysis_result=$(echo "${console_log}" | python3 "${analysis_script}" 2>/dev/null)
    local analysis_exit_code=$?

    # Clean up temporary script
    rm -f "${analysis_script}"

    if [[ ${analysis_exit_code} -eq 0 ]] && [[ -n "${analysis_result}" ]]; then
        echo "[SUCCESS] Gemini analysis completed"
        echo "${analysis_result}"
        return 0
    else
        echo "[ERROR] Gemini analysis failed"
        return 1
    fi
}

# Inform the user about final status of build
terminate() {
    case ${1:?} in
        ## Success
        0)
            local string="<b>done</b> (<a href=\"${BUILD_URL}\">#${BUILD_ID}</a>)"
        ;;
        ## Failure
        1)
            local string="<b>failed!</b> (<a href=\"${BUILD_URL}\">#${BUILD_ID}</a>)
View <a href=\"${BUILD_URL}consoleText\">console logs</a> for more."

            # Try to analyze the failure with Gemini AI
            echo "[INFO] Attempting to analyze build failure with AI..."
            local analysis
            analysis=$(analyze_jenkins_log)
            if [[ $? -eq 0 ]] && [[ -n "${analysis}" ]]; then
                # Send analysis as a separate message to avoid telegram message limits
                echo "[INFO] Sending AI analysis to Telegram..."
                local analysis_header="🤖 **AI Analysis of Build Failure:**

"
                sendTG reply "${START_MESSAGE_ID}" "${analysis_header}${analysis}"
            fi
        ;;
        ## Aborted
        2)
        local string="<b>aborted!</b> (<a href=\"${BUILD_URL}\">#${BUILD_ID}</a>)
Branch already exists on <a href=\"https://$GITLAB_SERVER/$ORG/$repo/tree/$branch/\">GitLab</a> (<code>$branch</code>)."
        ;;
    esac

    ## Template
    sendTG reply "${START_MESSAGE_ID}" "<b>Job</b> ${string}"
    exit "${1:?}"
}

# NOTE: urlEncode function removed - no longer needed with Redis messaging

curl --compressed --fail-with-body --silent --location "https://$GITLAB_SERVER" > /dev/null || {
    if _json="$(sendTG normal "Can't access $GITLAB_SERVER, cancelling job!")"; then
        CURL_MSG_ID="$(jq ".result.message_id" <<< "${_json}")"
        sendTG reply "${CURL_MSG_ID}" "<b>Job failed!</b>"
    fi
    exit 1
}

# Check if link is in whitelist.
mapfile -t LIST < "${HOME}/dumpbot/whitelist.txt"

## Set 'WHITELISTED' to true if download link (sub-)domain is present 
for WHITELISTED_LINKS in "${LIST[@]}"; do
    if [[ "${URL}" == *"${WHITELISTED_LINKS}"* ]]; then
        WHITELISTED=true
        break
    else
        WHITELISTED=false
    fi
done

## Print if link will be published, or not.
if [ "${ADD_BLACKLIST}" == true ] || [ "${WHITELISTED}" == false ]; then
    echo "[INFO] Download link will not be published on channel."
elif [ "${ADD_BLACKLIST}" == false ] && [ "${WHITELISTED}" == true ]; then
    echo "[INFO] Download link will be published on channel."
fi

if [[ -f $URL ]]; then
    cp -v "$URL" .  
    MESSAGE="<code>Found file locally.</code>"
    if _json="$(sendTG normal "${MESSAGE}")"; then
        # Store both message IDs
        MESSAGE_ID="$(jq ".result.message_id" <<< "${_json}")"
        START_MESSAGE_ID="${MESSAGE_ID}"
    else
        # disable sendTG and sendTG_edit_wrapper if wasn't able to send initial message
        sendTG() { :; } && sendTG_edit_wrapper() { :; }
    fi
else
    if [[ "$JOB_NAME" == *"privdump"* ]]; then
        MESSAGE="<code>Started private dump on</code> <a href=\"$BUILD_URL\">jenkins</a>"
    else
        MESSAGE="<code>Started</code> <a href=\"${URL}\">dump</a> <code>on</code> <a href=\"$BUILD_URL\">jenkins</a>"
    fi
    MESSAGE+=$'\n'"<b>Job ID:</b> <code>$BUILD_ID</code>."
    if _json="$(sendTG_with_cancel cancel_reply "${INITIAL_MESSAGE_ID}" "${MESSAGE}")"; then
        # Store both message IDs
        MESSAGE_ID="$(jq ".result.message_id" <<< "${_json}")"
        START_MESSAGE_ID="${MESSAGE_ID}"
    else
        # disable sendTG and sendTG_edit_wrapper if wasn't able to send initial message
        sendTG() { :; } && sendTG_edit_wrapper() { :; } && sendTG_with_cancel() { :; }
    fi

    # Override '${URL}' with best possible mirror of it
    case "${URL}" in
        # For Xiaomi: replace '${URL}' with (one of) the fastest mirror
        *"d.miui.com"*)
            # Do not run this loop in case we're already using one of the reccomended mirrors
            if ! echo "${URL}" | rg -q 'cdnorg|bkt-sgp-miui-ota-update-alisgp'; then
                # Set '${URL_ORIGINAL}' and '${FILE_PATH}' in case we might need to roll back
                URL_ORIGINAL=$(echo "${URL}" | sed -E 's|(https://[^/]+).*|\1|')
                FILE_PATH=$(echo ${URL#*d.miui.com/} | sed 's/?.*//')

                # Array of different possible mirrors
                MIRRORS=(
                    "https://cdnorg.d.miui.com"
                    "https://bkt-sgp-miui-ota-update-alisgp.oss-ap-southeast-1.aliyuncs.com"
                    "https://bn.d.miui.com"
                    "${URL_ORIGINAL}"
                )

                # Check back and forth for the best available mirror
                for URLS in "${MIRRORS[@]}"; do
                    # Change mirror's domain with one(s) from array
                    URL=${URLS}/${FILE_PATH}

                    # Be sure that the mirror is available. Once found, break the loop 
                    if [ "$(curl -I -sS "${URL}" | head -n1 | cut -d' ' -f2)" == "404" ]; then
                        echo "[ERROR] ${URLS} is not available. Trying with other mirror(s)..."
                    else
                        echo "[INFO] Found best available mirror."
                        break
                    fi
                done
            fi
        ;;
        # For Pixeldrain: replace the link with a direct one
        *"pixeldrain.com/u"*)
            echo "[INFO] Replacing with best available mirror."
            URL="https://pd.cybar.xyz/${URL##*/}"
        ;;
        *"pixeldrain.com/d"*)
            echo "[INFO] Replacing with direct download link."
            URL="https://pixeldrain.com/api/filesystem/${URL##*/}"
        ;;
    esac

    # Confirm download has started
    sendTG_edit_wrapper temporary "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Downloading the file...</code>" > /dev/null
    echo "[INFO] Started downloading... ($(date +%R:%S))"

    # downloadError: Kill the script in case downloading failed
    downloadError() {
        echo "Download failed. Exiting."
        sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Failed to download the file.</code>" > /dev/null
        terminate 1
    }

    # Properly check for different hosting websties.
    case ${URL} in
        *drive.google.com*)
            uvx gdown@5.2.0 -q "${URL}" --fuzzy > /dev/null || downloadError
        ;;
        *mediafire.com*)
           uvx --from git+https://github.com/Juvenal-Yescas/mediafire-dl@master mediafire-dl "${URL}" > /dev/null || downloadError
        ;;
        *mega.nz*)
            megatools dl "${URL}" > /dev/null || downloadError
        ;;
        *)
            aria2c -q -s16 -x16 --check-certificate=false "${URL}" || {
                rm -fv ./*
                wget -q --no-check-certificate "${URL}" || downloadError
            }
        ;;
    esac
    sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Downloaded the file.</code>" > /dev/null
    echo "[INFO] Finished downloading the file. ($(date +%R:%S))"
fi

# Clean query strings if any from URL
oldifs=$IFS
IFS="?"
read -ra CLEANED <<< "${URL}"
URL=${CLEANED[0]}
IFS=$oldifs

FILE=${URL##*/}
EXTENSION=${URL##*.}
UNZIP_DIR=${FILE/.$EXTENSION/}
export UNZIP_DIR

if [[ ! -f ${FILE} ]]; then
    FILE="$(find . -type f)"
    if [[ "$(wc -l <<< "${FILE}")" != 1 ]]; then
        sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Can't seem to find downloaded file!</code>" > /dev/null
        terminate 1
    fi
fi

if [[ "${USE_ALT_DUMPER}" == "false" ]]; then
    sendTG_edit_wrapper temporary "${MESSAGE_ID}" "${MESSAGE}"$'\n'"Extracting firmware with Python dumper..." > /dev/null
    uvx dumpyara "${FILE}" -o "${PWD}" || {
        sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Extraction failed!</code>" > /dev/null
        terminate 1
    }
else
    # Clone necessary tools
    if ! [[ -d "${HOME}/Firmware_extractor" ]]; then
        git clone -q https://github.com/AndroidDumps/Firmware_extractor "${HOME}/Firmware_extractor"
    else
        git -C "${HOME}/Firmware_extractor" pull -q --rebase
    fi

    sendTG_edit_wrapper temporary "${MESSAGE_ID}" "${MESSAGE}"$'\n'"Extracting firmware with alternative dumper..." > /dev/null
    bash "${HOME}"/Firmware_extractor/extractor.sh "${FILE}" "${PWD}" || {
        sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Extraction failed!</code>" > /dev/null
        terminate 1
    }

    PARTITIONS=(system systemex system_ext system_other
        vendor cust odm odm_ext oem factory product modem
        xrom oppo_product opproduct reserve india my_preload 
        my_odm my_stock my_operator my_country my_product my_company 
        my_engineering my_heytap my_custom my_manifest my_carrier my_region 
        my_bigball my_version special_preload vendor_dlkm odm_dlkm system_dlkm 
        mi_ext radio product_h preas preavs preload
    )

    sendTG_edit_wrapper temporary "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Extracting partitions...</code>" > /dev/null

    # Set commonly used binary names
    FSCK_EROFS="${HOME}/Firmware_extractor/tools/fsck.erofs"
    EXT2RD="${HOME}/Firmware_extractor/tools/ext2rd"

    # Extract the images
    for p in "${PARTITIONS[@]}"; do
        if [[ -f $p.img ]]; then
            # Create a folder for each partition
            mkdir "$p" || rm -rf "${p:?}"/*

            # Try to extract images via 'fsck.erofs'
            echo "[INFO] Extracting '$p' via 'fsck.erofs'..."
            ${FSCK_EROFS} --extract="$p" "$p".img >> /dev/null 2>&1 || {
                echo "[WARN] Extraction via 'fsck.erofs' failed."

                # Uses 'ext2rd' if images could not be extracted via 'fsck.erofs'
                echo "[INFO] Extracting '$p' via 'ext2rd'..."
                ${EXT2RD} "$p".img ./:"${p}" > /dev/null || {
                    echo "[WARN] Extraction via 'ext2rd' failed."

                    # Uses '7zz' if images could not be extracted via 'ext2rd'
                    echo "[INFO] Extracting '$p' via '7zz'..."
                    7zz -snld x "$p".img -y -o"$p"/ > /dev/null || {
                        echo "[ERROR] Extraction via '7zz' failed."

                        # Only abort if we're at the first occourence
                        if [[ "${p}" == "${PARTITIONS[0]}" ]]; then
                            # In case of failure, bail out and abort dumping altogether
                            sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Extraction failed!</code>" > /dev/null
                            terminate 1
                        fi
                    }
                }
            }

            # Clean-up
            rm -f "$p".img
        fi
    done

    # Also extract 'fsg.mbn' from 'radio.img'
    if [ -f "${PWD}/fsg.mbn" ]; then
        echo "[INFO] Extracting 'fsg.mbn' via '7zz'..."

        # Create '${PWD}/radio/fsg'
        mkdir "${PWD}"/radio/fsg

        # Thankfully, 'fsg.mbn' is a simple EXT2 partition
        7zz -snld x "${PWD}/fsg.mbn" -o"${PWD}/radio/fsg" > /dev/null

        # Remove 'fsg.mbn'
        rm -rf "${PWD}/fsg.mbn"
    fi
fi

rm -f "$FILE"

for image in init_boot.img vendor_kernel_boot.img vendor_boot.img boot.img dtbo.img; do
    if [[ ! -f ${image} ]]; then
        x=$(find . -type f -name "${image}")
        if [[ -n $x ]]; then
            mv -v "$x" "${image}"
        fi
    fi
done

# Extract kernel, device-tree blobs [...]
## Set commonly used tools
UNPACKBOOTIMG="${HOME}/Firmware_extractor/tools/unpackbootimg"

# Extract 'boot.img'
if [[ -f "${PWD}/boot.img" ]]; then
    # Set a variable for each path
    ## Image
    IMAGE=${PWD}/boot.img

    ## Output
    OUTPUT=${PWD}/boot

    # Python rewrite automatically extracts such partitions
    if [[ "${USE_ALT_DUMPER}" == "true" ]]; then
        mkdir -p "${OUTPUT}/ramdisk"

        # Unpack 'boot.img' through 'unpackbootimg'
        echo "[INFO] Extracting 'boot.img' content..."
        ${UNPACKBOOTIMG} -i "${IMAGE}" -o "${OUTPUT}" > /dev/null || \
            echo "[ERROR] Extraction unsuccessful."

        # Decrompress 'boot.img-ramdisk'
        ## Run only if 'boot.img-ramdisk' is not empty
        if file boot.img-ramdisk | grep -q LZ4 || file boot.img-ramdisk | grep -q gzip; then
            echo "[INFO] Extracting ramdisk..."
            unlz4 "${OUTPUT}/boot.img-ramdisk" "${OUTPUT}/ramdisk.lz4" > /dev/null
            7zz -snld x "${OUTPUT}/ramdisk.lz4" -o"${OUTPUT}/ramdisk" > /dev/null || \
                echo "[ERROR] Failed to extract ramdisk."

            ## Clean-up
            rm -rf "${OUTPUT}/ramdisk.lz4"
        fi
    fi

    # Extract 'ikconfig'
    echo "[INFO] Extract 'ikconfig'..."
    if command -v extract-ikconfig > /dev/null ; then
        extract-ikconfig "${PWD}"/boot.img > "${PWD}"/ikconfig || {
            echo "[ERROR] Failed to generate 'ikconfig'"
        }
    fi

    # Generate non-stack symbols
    echo "[INFO] Generating 'kallsyms.txt'..."
    uvx --from git+https://github.com/marin-m/vmlinux-to-elf@master kallsyms-finder "${IMAGE}" > kallsyms.txt || \
        echo "[ERROR] Failed to generate 'kallsyms.txt'"

    # Generate analyzable '.elf'
    echo "[INFO] Extracting 'boot.elf'..."
    uvx --from git+https://github.com/marin-m/vmlinux-to-elf@master vmlinux-to-elf "${IMAGE}" boot.elf > /dev/null ||
        echo "[ERROR] Failed to generate 'boot.elf'"

    # Create necessary directories
    mkdir -p "${OUTPUT}/dts" "${OUTPUT}/dtb"

    # Extract device-tree blobs from 'boot.img'
    echo "[INFO] boot.img: Extracting device-tree blobs..."
    extract-dtb "${IMAGE}" -o "${OUTPUT}/dtb" > /dev/null || \
        echo "[INFO] No device-tree blobs found."
    rm -rf "${OUTPUT}/dtb/00_kernel"

    # Do not run 'dtc' if no DTB was found
    if [ "$(find "${OUTPUT}/dtb" -name "*.dtb")" ]; then
        echo "[INFO] Decompiling device-tree blobs..."
        # Decompile '.dtb' to '.dts'
        for dtb in $(find "${PWD}/boot/dtb" -type f); do
            dtc -q -I dtb -O dts "${dtb}" >> "${OUTPUT}/dts/$(basename "${dtb}" .dtb).dts" || \
                echo "[ERROR] Failed to decompile."
        done
    fi
fi

# Extract 'vendor_boot.img'
if [[ -f "${PWD}/vendor_boot.img" ]]; then
    # Set a variable for each path
    ## Image
    IMAGE=${PWD}/vendor_boot.img

    ## Output
    OUTPUT=${PWD}/vendor_boot

    # Python rewrite automatically extracts such partitions
    if [[ "${USE_ALT_DUMPER}" == "true" ]]; then
        mkdir -p "${OUTPUT}/ramdisk"

        ## Unpack 'vendor_boot.img' through 'unpackbootimg'
        echo "[INFO] Extracting 'vendor_boot.img' content..."
        ${UNPACKBOOTIMG} -i "${IMAGE}" -o "${OUTPUT}" > /dev/null || \
            echo "[ERROR] Extraction unsuccessful."

        # Decrompress 'vendor_boot.img-vendor_ramdisk'
        echo "[INFO] Extracting ramdisk..."
        unlz4 "${OUTPUT}/vendor_boot.img-vendor_ramdisk" "${OUTPUT}/ramdisk.lz4" > /dev/null
        7zz -snld x "${OUTPUT}/ramdisk.lz4" -o"${OUTPUT}/ramdisk" > /dev/null || \
            echo "[ERROR] Failed to extract ramdisk."

        ## Clean-up
        rm -rf "${OUTPUT}/ramdisk.lz4"
    fi

    # Create necessary directories
    mkdir -p "${OUTPUT}/dts" "${OUTPUT}/dtb"

    # Extract device-tree blobs from 'vendor_boot.img'
    echo "[INFO] vendor_boot.img: Extracting device-tree blobs..."
    extract-dtb "${IMAGE}" -o "${OUTPUT}/dtb" > /dev/null || \
        echo "[INFO] No device-tree blobs found."
    rm -rf "${OUTPUT}/dtb/00_kernel"

    # Decompile '.dtb' to '.dts'
    if [ "$(find "${OUTPUT}/dtb" -name "*.dtb")" ]; then
        echo "[INFO] Decompiling device-tree blobs..."
        # Decompile '.dtb' to '.dts'
        for dtb in $(find "${OUTPUT}/dtb" -type f); do
            dtc -q -I dtb -O dts "${dtb}" >> "${OUTPUT}/dts/$(basename "${dtb}" .dtb).dts" || \
                echo "[ERROR] Failed to decompile."
        done
    fi
fi

# Extract 'vendor_kernel_boot.img'
if [[ -f "${PWD}/vendor_kernel_boot.img" ]]; then
    # Set a variable for each path
    ## Image
    IMAGE=${PWD}/vendor_kernel_boot.img

    ## Output
    OUTPUT=${PWD}/vendor_kernel_boot

    # Python rewrite automatically extracts such partitions
    if [[ "${USE_ALT_DUMPER}" == "true" ]]; then
        mkdir -p "${OUTPUT}/ramdisk"

        # Unpack 'vendor_kernel_boot.img' through 'unpackbootimg'
        echo "[INFO] Extracting 'vendor_kernel_boot.img' content..."
        ${UNPACKBOOTIMG} -i "${IMAGE}" -o "${OUTPUT}" > /dev/null || \
            echo "[ERROR] Extraction unsuccessful."

        # Decrompress 'vendor_kernel_boot.img-vendor_ramdisk'
        echo "[INFO] Extracting ramdisk..."
        unlz4 "${OUTPUT}/vendor_kernel_boot.img-vendor_ramdisk" "${OUTPUT}/ramdisk.lz4" > /dev/null
        7zz -snld x "${OUTPUT}/ramdisk.lz4" -o"${OUTPUT}/ramdisk" > /dev/null || \
            echo "[ERROR] Failed to extract ramdisk."

        ## Clean-up
        rm -rf "${OUTPUT}/ramdisk.lz4"
    fi

    # Create necessary directories
    mkdir -p "${OUTPUT}/dts" "${OUTPUT}/dtb"

    # Extract device-tree blobs from 'vendor_kernel_boot.img'
    echo "[INFO] vendor_kernel_boot.img: Extracting device-tree blobs..."
    extract-dtb "${IMAGE}" -o "${OUTPUT}/dtb" > /dev/null || \
        echo "[INFO] No device-tree blobs found."
    rm -rf "${OUTPUT}/dtb/00_kernel"

    # Decompile '.dtb' to '.dts'
    if [ "$(find "${OUTPUT}/dtb" -name "*.dtb")" ]; then
        echo "[INFO] Decompiling device-tree blobs..."
        # Decompile '.dtb' to '.dts'
        for dtb in $(find "${OUTPUT}/dtb" -type f); do
            dtc -q -I dtb -O dts "${dtb}" >> "${OUTPUT}/dts/$(basename "${dtb}" .dtb).dts" || \
                echo "[ERROR] Failed to decompile."
        done
    fi
fi

# Extract 'init_boot.img'
if [[ -f "${PWD}/init_boot.img" ]] && [[ "${USE_ALT_DUMPER}" == "true" ]]; then
    # Set a variable for each path
    ## Image
    IMAGE=${PWD}/init_boot.img

    ## Output
    OUTPUT=${PWD}/init_boot

    # Create necessary directories
    mkdir -p "${OUTPUT}/ramdisk"

    # Unpack 'init_boot.img' through 'unpackbootimg'
    echo "[INFO] Extracting 'init_boot.img' content..."
    ${UNPACKBOOTIMG} -i "${IMAGE}" -o "${OUTPUT}" > /dev/null || \
        echo "[ERROR] Extraction unsuccessful."

    # Decrompress 'init_boot.img-ramdisk'
    echo "[INFO] Extracting ramdisk..."
    unlz4 "${OUTPUT}/init_boot.img-ramdisk" "${OUTPUT}/ramdisk.lz4" > /dev/null
    7zz -snld x "${OUTPUT}/ramdisk.lz4" -o"${OUTPUT}/ramdisk" > /dev/null || \
        echo "[ERROR] Failed to extract ramdisk."

    ## Clean-up
    rm -rf "${OUTPUT}/ramdisk.lz4"
fi

# Extract 'dtbo.img'
if [[ -f "${PWD}/dtbo.img" ]]; then
    # Set a variable for each path
    ## Image
    IMAGE=${PWD}/dtbo.img

    ## Output
    OUTPUT=${PWD}/dtbo

    # Create necessary directories
    mkdir -p "${OUTPUT}/dts"

    # Extract device-tree blobs from 'dtbo.img'
    echo "[INFO] dbto.img: Extracting device-tree blobs..."
    extract-dtb "${IMAGE}" -o "${OUTPUT}" > /dev/null || \
        echo "[INFO] No device-tree blobs found."
    rm -rf "${OUTPUT}/00_kernel"

    # Decompile '.dtb' to '.dts'
    echo "[INFO] Decompiling device-tree blobs..."
    for dtb in $(find "${OUTPUT}" -type f); do
        dtc -q -I dtb -O dts "${dtb}" >> "${OUTPUT}/dts/$(basename "${dtb}" .dtb).dts" || \
            echo "[ERROR] Failed to decompile."
    done
fi

# Oppo/Realme/OnePlus devices have some images in folders, extract those
for dir in "vendor/euclid" "system/system/euclid" "reserve/reserve"; do
    [[ -d ${dir} ]] && {
        pushd "${dir}" || terminate 1
        for f in *.img; do
            [[ -f $f ]] || continue
            sendTG_edit_wrapper temporary "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Partition Name: ${p}</code>" > /dev/null
            7zz -snld x "$f" -o"${f/.img/}" > /dev/null
            rm -fv "$f"
        done
        popd || terminate 1
    }
done

sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>All partitions extracted.</code>" > /dev/null

# Generate 'board-info.txt'
echo "[INFO] Generating 'board-info.txt'..."

## Generic
if [ -f ./vendor/build.prop ]; then
    strings ./vendor/build.prop | grep "ro.vendor.build.date.utc" | sed "s|ro.vendor.build.date.utc|require version-vendor|g" >> ./board-info.txt
fi

## Qualcomm-specific
if [[ $(find . -name "modem") ]] && [[ $(find . -name "*./tz*") ]]; then
    find ./modem -type f -exec strings {} \; | rg "QC_IMAGE_VERSION_STRING=MPSS." | sed "s|QC_IMAGE_VERSION_STRING=MPSS.||g" | cut -c 4- | sed -e 's/^/require version-baseband=/' >> "${PWD}"/board-info.txt
    find ./tz* -type f -exec strings {} \; | rg "QC_IMAGE_VERSION_STRING" | sed "s|QC_IMAGE_VERSION_STRING|require version-trustzone|g" >> "${PWD}"/board-info.txt
fi

## Sort 'board-info.txt' content
if [ -f "${PWD}"/board-info.txt ]; then
    sort -u -o ./board-info.txt ./board-info.txt
fi

# Prop extraction
echo "[INFO] Extracting properties..."
sendTG_edit_wrapper temporary "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Extracting properties...</code>" > /dev/null

oplus_pipeline_key=$(rg -m1 -INoP --no-messages "(?<=^ro.oplus.pipeline_key=).*" my_manifest/build*.prop)
honor_product_base_version=$(rg -m1 -INoP --no-messages "(?<=^ro.comp.hl.product_base_version=).*" product_h/etc/prop/local*.prop)

flavor=$(rg -m1 -INoP --no-messages "(?<=^ro.build.flavor=).*" {vendor,system,system/system}/build.prop)
[[ -z ${flavor} ]] && flavor=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.flavor=).*" vendor/build*.prop)
[[ -z ${flavor} ]] && flavor=$(rg -m1 -INoP --no-messages "(?<=^ro.build.flavor=).*" {vendor,system,system/system}/build*.prop)
[[ -z ${flavor} ]] && flavor=$(rg -m1 -INoP --no-messages "(?<=^ro.system.build.flavor=).*" {system,system/system}/build*.prop)
[[ -z ${flavor} ]] && flavor=$(rg -m1 -INoP --no-messages "(?<=^ro.build.type=).*" {system,system/system}/build*.prop)

release=$(rg -m1 -INoP --no-messages "(?<=^ro.build.version.release=).*" {my_manifest,vendor,system,system/system}/build*.prop)
[[ -z ${release} ]] && release=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.version.release=).*" vendor/build*.prop)
[[ -z ${release} ]] && release=$(rg -m1 -INoP --no-messages "(?<=^ro.system.build.version.release=).*" {system,system/system}/build*.prop)
release=$(echo "$release" | head -1)

id=$(rg -m1 -INoP --no-messages "(?<=^ro.build.id=).*" my_manifest/build*.prop)
[[ -z ${id} ]] && id=$(rg -m1 -INoP --no-messages "(?<=^ro.build.id=).*" system/system/build_default.prop)
[[ -z ${id} ]] && id=$(rg -m1 -INoP --no-messages "(?<=^ro.build.id=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${id} ]] && id=$(rg -m1 -INoP --no-messages "(?<=^ro.build.id=).*" {vendor,system,system/system}/build*.prop)
[[ -z ${id} ]] && id=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.id=).*" vendor/build*.prop)
[[ -z ${id} ]] && id=$(rg -m1 -INoP --no-messages "(?<=^ro.system.build.id=).*" {system,system/system}/build*.prop)
id=$(echo "$id" | head -1)

incremental=$(rg -m1 -INoP --no-messages "(?<=^ro.build.version.incremental=).*" my_manifest/build*.prop)
[[ -z ${incremental} ]] && incremental=$(rg -m1 -INoP --no-messages "(?<=^ro.build.version.incremental=).*" system/system/build_default.prop)
[[ -z ${incremental} ]] && incremental=$(rg -m1 -INoP --no-messages "(?<=^ro.build.version.incremental=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${incremental} ]] && incremental=$(rg -m1 -INoP --no-messages "(?<=^ro.build.version.incremental=).*" {vendor,system,system/system}/build*.prop | head -1)
[[ -z ${incremental} ]] && incremental=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.version.incremental=).*" my_manifest/build*.prop)
[[ -z ${incremental} ]] && incremental=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.version.incremental=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${incremental} ]] && incremental=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.version.incremental=).*" vendor/build*.prop)
[[ -z ${incremental} ]] && incremental=$(rg -m1 -INoP --no-messages "(?<=^ro.system.build.version.incremental=).*" {system,system/system}/build*.prop | head -1)
[[ -z ${incremental} ]] && incremental=$(rg -m1 -INoP --no-messages "(?<=^ro.build.version.incremental=).*" my_product/build*.prop)
[[ -z ${incremental} ]] && incremental=$(rg -m1 -INoP --no-messages "(?<=^ro.system.build.version.incremental=).*" my_product/build*.prop)
[[ -z ${incremental} ]] && incremental=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.version.incremental=).*" my_product/build*.prop)
incremental=$(echo "$incremental" | head -1)

tags=$(rg -m1 -INoP --no-messages "(?<=^ro.build.tags=).*" {vendor,system,system/system}/build*.prop)
[[ -z ${tags} ]] && tags=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.tags=).*" vendor/build*.prop)
[[ -z ${tags} ]] && tags=$(rg -m1 -INoP --no-messages "(?<=^ro.system.build.tags=).*" {system,system/system}/build*.prop)
tags=$(echo "$tags" | head -1)

platform=$(rg -m1 -INoP --no-messages "(?<=^ro.board.platform=).*" {vendor,system,system/system}/build*.prop | head -1)
[[ -z ${platform} ]] && platform=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.board.platform=).*" vendor/build*.prop)
[[ -z ${platform} ]] && platform=$(rg -m1 -INoP --no-messages rg"(?<=^ro.system.board.platform=).*" {system,system/system}/build*.prop)
platform=$(echo "$platform" | head -1)

manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.manufacturer=).*" odm/etc/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.manufacturer=).*" odm/etc/fingerprint/build.default.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.manufacturer=).*" my_product/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.manufacturer=).*" my_manifest/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.manufacturer=).*" system/system/build_default.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.manufacturer=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.manufacturer=).*" {vendor,system,system/system}/build*.prop | head -1)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.brand.sub=).*" my_product/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.brand.sub=).*" system/system/euclid/my_product/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.product.manufacturer=).*" vendor/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.manufacturer=).*" my_manifest/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.manufacturer=).*" system/system/build_default.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.manufacturer=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.manufacturer=).*" vendor/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.system.product.manufacturer=).*" {system,system/system}/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.system.manufacturer=).*" {system,system/system}/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.manufacturer=).*" my_manifest/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.manufacturer=).*" system/system/build_default.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.manufacturer=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.manufacturer=).*" vendor/odm/etc/build*.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.manufacturer=).*" {oppo_product,my_product}/build*.prop | head -1)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.manufacturer=).*" vendor/euclid/*/build.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.system.product.manufacturer=).*" vendor/euclid/*/build.prop)
[[ -z ${manufacturer} ]] && manufacturer=$(rg -m1 -INoP --no-messages "(?<=^ro.product.product.manufacturer=).*" vendor/euclid/product/build*.prop)
manufacturer=$(echo "$manufacturer" | head -1)

fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.odm.build.fingerprint=).*" odm/etc/*build*.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.fingerprint=).*" my_manifest/build*.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.fingerprint=).*" system/system/build_default.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.fingerprint=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.fingerprint=).*" odm/etc/fingerprint/build.default.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.fingerprint=).*" vendor/build*.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.build.fingerprint=).*" my_manifest/build*.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.build.fingerprint=).*" system/system/build_default.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.build.fingerprint=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.build.fingerprint=).*"  {system,system/system}/build*.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.product.build.fingerprint=).*" product/build*.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.system.build.fingerprint=).*" {system,system/system}/build*.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.build.fingerprint=).*" my_product/build.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.system.build.fingerprint=).*" my_product/build.prop)
[[ -z ${fingerprint} ]] && fingerprint=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.fingerprint=).*" my_product/build.prop)
fingerprint=$(echo "$fingerprint" | head -1)

codename=$(rg -m1 -INoP --no-messages "(?<=^ro.build.product=).*" product_h/etc/prop/local*.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.device=).*" odm/etc/build*.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.device=).*" system/system/build_default.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.device=).*" odm/etc/fingerprint/build.default.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.device=).*" my_manifest/build*.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.device=).*" system/system/build_default.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.device=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.device=).*" system/system/build_default.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.device=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.product.device=).*" system/system/build_default.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.product.device=).*" vendor/build*.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.device=).*" vendor/build*.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.device=).*" {vendor,system,system/system}/build*.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.product.device.oem=).*" odm/build.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.product.device.oem=).*" vendor/euclid/odm/build.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.device=).*" my_manifest/build*.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.system.device=).*" {system,system/system}/build*.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.system.device=).*" vendor/euclid/*/build.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.product.device=).*" vendor/euclid/*/build.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.product.device=).*" system/system/build_default.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.product.model=).*" vendor/euclid/*/build.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.device=).*" {oppo_product,my_product}/build*.prop | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.product.device=).*" oppo_product/build*.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.system.device=).*" my_product/build*.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.device=).*" my_product/build*.prop)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.build.fota.version=).*" {system,system/system}/build*.prop | cut -d - -f1 | head -1)
[[ -z ${codename} ]] && codename=$(rg -m1 -INoP --no-messages "(?<=^ro.build.product=).*" {vendor,system,system/system}/build*.prop | head -1)
[[ -z ${codename} ]] && codename=$(echo "$fingerprint" | cut -d / -f3 | cut -d : -f1)
[[ -z $codename ]] && {
    sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Codename not detected! Aborting!</code>" > /dev/null
    terminate 1
}

brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.brand=).*" odm/etc/"${codename}"_build.prop | head -1)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.brand=).*" odm/etc/build*.prop | head -1)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.brand=).*" system/system/build_default.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.brand=).*" odm/etc/fingerprint/build.default.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.brand=).*" my_product/build*.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.brand=).*" system/system/build_default.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.brand=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.brand=).*" {vendor,system,system/system}/build*.prop | head -1)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.brand.sub=).*" my_product/build*.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.brand.sub=).*" system/system/euclid/my_product/build*.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.brand=).*" my_manifest/build*.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.brand=).*" system/system/build_default.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.brand=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.vendor.brand=).*" vendor/build*.prop | head -1)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.product.brand=).*" vendor/build*.prop | head -1)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.system.brand=).*" {system,system/system}/build*.prop | head -1)
[[ -z ${brand} || ${brand} == "OPPO" ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.system.brand=).*" vendor/euclid/*/build.prop | head -1)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.product.brand=).*" vendor/euclid/product/build*.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.brand=).*" my_manifest/build*.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.brand=).*" vendor/euclid/my_manifest/build.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.odm.brand=).*" vendor/odm/etc/build*.prop)
[[ -z ${brand} ]] && brand=$(rg -m1 -INoP --no-messages "(?<=^ro.product.brand=).*" {oppo_product,my_product}/build*.prop | head -1)
[[ -z ${brand} ]] && brand=$(echo "$fingerprint" | cut -d / -f1)
[[ -z ${brand} ]] && brand="$manufacturer"

description=$(rg -m1 -INoP --no-messages "(?<=^ro.build.description=).*" {system,system/system}/build.prop)
[[ -z ${description} ]] && description=$(rg -m1 -INoP --no-messages "(?<=^ro.build.description=).*" {system,system/system}/build*.prop)
[[ -z ${description} ]] && description=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.description=).*" vendor/build.prop)
[[ -z ${description} ]] && description=$(rg -m1 -INoP --no-messages "(?<=^ro.vendor.build.description=).*" vendor/build*.prop)
[[ -z ${description} ]] && description=$(rg -m1 -INoP --no-messages "(?<=^ro.product.build.description=).*" product/build.prop)
[[ -z ${description} ]] && description=$(rg -m1 -INoP --no-messages "(?<=^ro.product.build.description=).*" product/build*.prop)
[[ -z ${description} ]] && description=$(rg -m1 -INoP --no-messages "(?<=^ro.system.build.description=).*" {system,system/system}/build*.prop)
[[ -z ${description} ]] && description="$flavor $release $id $incremental $tags"

# In case there's an additional space on the 'description', 
# remove it as it prevents 'git' from creating a branch.
if [[ $(echo "${description}" | head -c1) == " " ]]; then
    description=$(echo "${description}" | sed s/'\s'//)
fi

is_ab=$(rg -m1 -INoP --no-messages "(?<=^ro.build.ab_update=).*" {system,system/system,vendor}/build*.prop)
is_ab=$(echo "$is_ab" | head -1)
[[ -z ${is_ab} ]] && is_ab="false"

codename=$(echo "$codename" | tr ' ' '_')

# Append 'oplus_pipeline_key' in case it's set
if [[ -n "${oplus_pipeline_key}" ]]; then
    branch=$(echo "${description}"--"${oplus_pipeline_key}" | head -1 | tr ' ' '-')
# Append 'honor_product_base_version' in case it's set
elif [[ -n "${honor_product_base_version}" ]]; then
    branch=$(echo "${description}"--"${honor_product_base_version}" | head -1 | tr ' ' '-')
else
    branch=$(echo "$description" | head -1 | tr ' ' '-')
fi

repo_subgroup=$(echo "$brand" | tr '[:upper:]' '[:lower:]')
[[ -z $repo_subgroup ]] && repo_subgroup=$(echo "$manufacturer" | tr '[:upper:]' '[:lower:]')
repo_name=$(echo "$codename" | tr '[:upper:]' '[:lower:]')
repo="$repo_subgroup/$repo_name"
platform=$(echo "$platform" | tr '[:upper:]' '[:lower:]' | tr -dc '[:print:]' | tr '_' '-' | cut -c 1-35)
top_codename=$(echo "$codename" | tr '[:upper:]' '[:lower:]' | tr -dc '[:print:]' | tr '_' '-' | cut -c 1-35)
manufacturer=$(echo "$manufacturer" | tr '[:upper:]' '[:lower:]' | tr -dc '[:print:]' | tr '_' '-' | cut -c 1-35)

sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>All props extracted.</code>" > /dev/null

printf "%s\n" "flavor: ${flavor}
release: ${release}
id: ${id}
incremental: ${incremental}
tags: ${tags}
fingerprint: ${fingerprint}
brand: ${brand}
codename: ${codename}
description: ${description}
branch: ${branch}
repo: ${repo}
manufacturer: ${manufacturer}
platform: ${platform}
top_codename: ${top_codename}
is_ab: ${is_ab}"

# Generate device tree ('aospdtgen')
sendTG_edit_wrapper temporary "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Generating device tree...</code>" > /dev/null
mkdir -p aosp-device-tree

echo "[INFO] Generating device tree..."
if uvx aospdtgen@1.1.1 . --output ./aosp-device-tree > /dev/null; then
    sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Device tree successfully generated.</code>" > /dev/null
else
    echo "[ERROR] Failed to generate device tree."
    sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Failed to generate device tree.</code>" > /dev/null
fi

# Generate 'all_files.txt'
echo "[INFO] Generating 'all_files.txt'..."
find . -type f ! -name all_files.txt -and ! -path "*/aosp-device-tree/*" -printf '%P\n' | sort | grep -v ".git/" > ./all_files.txt

# Check whether the subgroup exists or not
if ! group_id_json="$(curl --compressed --fail-with-body -sH "Authorization: Bearer $DUMPER_TOKEN" "https://$GITLAB_SERVER/api/v4/groups/$ORG%2f$repo_subgroup")"; then
    echo "Response: $group_id_json"
    if ! group_id_json="$(curl --compressed --fail-with-body -sH "Authorization: Bearer $DUMPER_TOKEN" "https://$GITLAB_SERVER/api/v4/groups" -X POST -F name="${repo_subgroup^}" -F parent_id=64 -F path="${repo_subgroup}" -F visibility=public)"; then
        echo "Creating subgroup for $repo_subgroup failed"
        echo "Response: $group_id_json"
        sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Creating subgroup for $repo_subgroup failed!</code>" > /dev/null
    fi
fi

if ! group_id="$(jq '.id' -e <<< "${group_id_json}")"; then
    echo "Unable to get gitlab group id"
    sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Unable to get gitlab group id!</code>" > /dev/null
    terminate 1
fi

# Create the repo if it doesn't exist
project_id_json="$(curl --compressed -sH "Authorization: bearer ${DUMPER_TOKEN}" "https://$GITLAB_SERVER/api/v4/projects/$ORG%2f$repo_subgroup%2f$repo_name")"
if ! project_id="$(jq .id -e <<< "${project_id_json}")"; then
    project_id_json="$(curl --compressed -sH "Authorization: bearer ${DUMPER_TOKEN}" "https://$GITLAB_SERVER/api/v4/projects" -X POST -F namespace_id="$group_id" -F name="$repo_name" -F visibility=public)"
    if ! project_id="$(jq .id -e <<< "${project_id_json}")"; then
        echo "Could get get project id"
        sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Could not get project id!</code>" > /dev/null
        terminate 1
    fi
fi

branch_json="$(curl --compressed -sH "Authorization: bearer ${DUMPER_TOKEN}" "https://$GITLAB_SERVER/api/v4/projects/$project_id/repository/branches/$branch")"
[[ "$(jq -r '.name' -e <<< "${branch_json}")" == "$branch" ]] && {
    echo "$branch already exists in $repo"
    sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>$branch already exists in</code> <a href=\"https://$GITLAB_SERVER/$ORG/$repo/tree/$branch/\">$repo</a>!" > /dev/null
    terminate 2
}

# Add, commit, and push after filtering out certain files
git init --initial-branch "$branch"
git config user.name "dumper"
git config user.email "dumper@$GITLAB_SERVER"

## Committing
echo "[INFO] Adding files and committing..."
sendTG_edit_wrapper temporary "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Committing...</code>" > /dev/null
git add --ignore-errors -A >> /dev/null 2>&1
git commit --quiet --signoff --message="$description" || {
    sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Committing failed!</code>" > /dev/null
    echo "[ERROR] Committing failed!"
    terminate 1
}

## Pushing
echo "[INFO] Pushing..."
sendTG_edit_wrapper temporary "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Pushing...</code>" > /dev/null
git push "$PUSH_HOST:$ORG/$repo.git" HEAD:refs/heads/"$branch" || {
    sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Pushing failed!</code>" > /dev/null
    echo "[ERROR] Pushing failed!"
    terminate 1
}

# Set default branch to the newly pushed branch
curl --compressed -s -H "Authorization: bearer ${DUMPER_TOKEN}" "https://$GITLAB_SERVER/api/v4/projects/$project_id" -X PUT -F default_branch="$branch" > /dev/null

# Send message to Telegram group
sendTG_edit_wrapper permanent "${MESSAGE_ID}" "${MESSAGE}"$'\n'"<code>Pushed</code> <a href=\"https://$GITLAB_SERVER/$ORG/$repo/tree/$branch/\">$description</a>" > /dev/null

## Only add this line in case URL is expected in the whitelist
if [ "${WHITELISTED}" == true ] && [ "${ADD_BLACKLIST}" == false ]; then
    link="[[firmware](${URL})]"
fi

echo -e "[INFO] Sending Telegram notification"
tg_text="**Brand**: \`$brand\`
**Device**: \`$codename\`
**Version**: \`$release\`
**Fingerprint**: \`$fingerprint\`
**Platform**: \`$platform\`
[[repo](https://$GITLAB_SERVER/$ORG/$repo/tree/$branch/)] $link"

# Send message to Telegram channel
curl --compressed -s "https://api.telegram.org/bot${API_KEY}/sendmessage" --data "text=${tg_text}&chat_id=@android_dumps&parse_mode=Markdown&disable_web_page_preview=True" > /dev/null

terminate 0