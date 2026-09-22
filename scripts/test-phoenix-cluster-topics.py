import os
import sys
import time
from kafka import KafkaAdminClient
from kafka.admin import NewTopic
from langboard_shared.Env import Env


DEAD_LETTER_PROBE_PREFIXES = (
    "socket_publish_dead_letter_browser_probe_",
    "socket_publish_dead_letter_cluster_probe_",
    "socket_publish_dead_letter_probe_",
)


def delete_dead_letter_probe(admin: KafkaAdminClient, topic: str) -> None:
    if not topic.startswith(DEAD_LETTER_PROBE_PREFIXES):
        raise ValueError("Refusing to delete a topic outside the dead-letter probe namespace")
    if topic in admin.list_topics():
        admin.delete_topics([topic])


def verify_assignments(admin: KafkaAdminClient, source: str) -> None:
    group_id = os.environ["PHOENIX_FANOUT_GROUP_ID"]
    deadline = time.monotonic() + 60
    assignments = []
    while time.monotonic() < deadline:
        group = admin.describe_consumer_groups([group_id])[0]
        if group.state == "Stable" and len(group.members) == 2:
            assignments = [
                [
                    partition
                    for topic, partitions in member.member_assignment.assignment
                    if topic == source
                    for partition in partitions
                ]
                for member in group.members
            ]
            if all(assignments) and sorted(partition for owned in assignments for partition in owned) == [0, 1, 2]:
                print(f"Verified two consumer owners for all source partitions: {assignments}", flush=True)
                return
        time.sleep(1)
    raise RuntimeError(f"Expected two stable owners with disjoint source partitions [0, 1, 2]: {assignments}")


def main() -> None:
    action = sys.argv[1]
    dead_letter = os.environ["PHOENIX_SOCKET_DLQ_TOPIC"]
    admin = KafkaAdminClient(bootstrap_servers=Env.BROADCAST_URLS)
    if action == "delete_dead_letter":
        try:
            delete_dead_letter_probe(admin, dead_letter)
        finally:
            admin.close()
        return

    source = os.environ["SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC"]
    if not source.startswith("socket_publish_cluster_probe_") or not dead_letter.startswith(
        "socket_publish_dead_letter_cluster_probe_"
    ):
        raise ValueError("Refusing to modify topics outside the cluster probe namespace")

    try:
        if action == "create":
            admin.create_topics(
                [
                    NewTopic(name=source, num_partitions=3, replication_factor=1),
                    NewTopic(name=dead_letter, num_partitions=1, replication_factor=1),
                ]
            )
        elif action == "delete":
            existing = {source, dead_letter} & set(admin.list_topics())
            if existing:
                admin.delete_topics(sorted(existing))
        elif action == "verify":
            verify_assignments(admin, source)
        else:
            raise ValueError("Expected create, delete, or verify")
    finally:
        admin.close()


if __name__ == "__main__":
    main()
