"""
WeChat message capture diagnostic tool.
Tests whether wcferry can receive messages at all, and shows raw message fields.

Run this while WeChat is logged in, then send a message to File Transfer Assistant.
"""

import logging
import queue
import sys
import time

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger("DIAGNOSE")


def step1_check_wechat_process():
    """Check if WeChat.exe is running and check version."""
    import subprocess
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq WeChat.exe"],
            capture_output=True, text=True, timeout=5,
        )
        if "WeChat.exe" in result.stdout:
            logger.info("✅ STEP 1: WeChat.exe process is running")
            # Check version
            try:
                ver = subprocess.run(
                    ["wmic", "datafile", "where", "name='C:\\Program Files\\Tencent\\WeChat\\WeChat.exe'",
                     "get", "Version", "/value"],
                    capture_output=True, text=True, timeout=5,
                )
                logger.info("   WeChat version: %s", ver.stdout.strip())
            except Exception:
                pass
            return True
        else:
            logger.error("❌ STEP 1: WeChat.exe is NOT running")
            return False
    except Exception as e:
        logger.error("❌ STEP 1: Failed to check WeChat process: %s", e)
        return False


def step2_connect_wcferry():
    """Try to connect to wcferry."""
    try:
        logger.info("STEP 2: Connecting to wcferry...")
        from wcferry import Wcf
        wcf = Wcf(debug=True)
        logger.info("✅ STEP 2: wcferry Wcf() connected successfully")
        logger.info("   Self wxid: %s", wcf.get_self_wxid())
        return wcf
    except Exception as e:
        logger.error("❌ STEP 2: wcferry connection FAILED: %s", e)
        return None


def step3_enable_receiving(wcf):
    """Enable message receiving."""
    try:
        logger.info("STEP 3: Enabling message receiving...")
        result = wcf.enable_receiving_msg()
        logger.info("✅ STEP 3: enable_receiving_msg() returned: %s", result)
        return True
    except Exception as e:
        logger.error("❌ STEP 3: enable_receiving_msg() FAILED: %s", e)
        return False


def step4_poll_messages(wcf, duration=60):
    """
    Poll for messages for `duration` seconds.
    Print ALL raw fields of any received message.
    """
    logger.info("STEP 4: Polling for messages (will run for %d seconds)...", duration)
    logger.info("   👉 NOW send a message to File Transfer Assistant (e.g. '/oc hello')")
    logger.info("")
    start = time.monotonic()
    count = 0

    while time.monotonic() - start < duration:
        try:
            msg = wcf.get_msg()
            count += 1
            logger.info("")
            logger.info("═══════════════════════════════════════")
            logger.info("📨 MESSAGE #%d RECEIVED!", count)
            logger.info("═══════════════════════════════════════")
            logger.info("   type:     %s (%d)", type(msg).__name__, msg.type)
            logger.info("   id:       %s", msg.id)
            logger.info("   ts:       %d", msg.ts)
            logger.info("   sender:   %s", msg.sender)
            logger.info("   roomid:   %s", msg.roomid)
            logger.info("   content:  %s", msg.content[:200] if msg.content else "(empty)")
            logger.info("   sign:     %s", msg.sign)
            logger.info("   xml:      %s", msg.xml[:200] if msg.xml else "(empty)")
            logger.info("")
            logger.info("   _is_self: %s", msg._is_self)
            logger.info("   _is_group:%s", msg._is_group)
            logger.info("   from_self:%s", msg.from_self())
            logger.info("   from_group:%s", msg.from_group())
            logger.info("   is_text:  %s", msg.is_text())
            logger.info("")

            # Check if it would pass our bridge filters
            if msg.type == 1:
                logger.info("   ✅ PASS: type=1 (TEXT)")
            else:
                logger.info("   ❌ BLOCKED: type=%d != TEXT", msg.type)

            if msg.from_self():
                logger.info("   ✅ PASS: from_self()=True")
            else:
                logger.info("   ❌ BLOCKED: from_self()=False")

            if msg.type == 1 and msg.from_self():
                logger.info("")
                logger.info("   ✅ This message WOULD reach the command router!")
            else:
                logger.info("")
                logger.info("   ❌ This message would be FILTERED OUT by bridge")

            logger.info("═══════════════════════════════════════")
            logger.info("")

        except queue.Empty:
            # Normal — no message yet
            if count == 0 and int(time.monotonic() - start) % 10 == 0:
                logger.info("   ... waiting for messages (%ds elapsed) ...", int(time.monotonic() - start))
        except Exception as e:
            logger.error("Error in message loop: %s", e)

    logger.info("")
    logger.info("STEP 4 complete: received %d message(s) in %d seconds", count, duration)


def main():
    print("=" * 60)
    print("  WeChat Message Capture Diagnostic")
    print("=" * 60)
    print("")

    # Step 1: Check WeChat process
    if not step1_check_wechat_process():
        sys.exit(1)

    # Step 2: Connect to wcferry
    wcf = step2_connect_wcferry()
    if wcf is None:
        sys.exit(1)

    # Step 3: Enable receiving
    if not step3_enable_receiving(wcf):
        wcf.cleanup()
        sys.exit(1)

    # Step 4: Poll for messages
    try:
        step4_poll_messages(wcf, duration=60)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        wcf.disable_recv_msg()
        wcf.cleanup()
        logger.info("Cleanup done")


if __name__ == "__main__":
    main()
