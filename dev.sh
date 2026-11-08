#!/usr/bin/env bash
# Test database: PostgreSQL with PostGIS on 127.0.0.1.
# Settings come from poe_tasks.toml [env] (poe passes them); the defaults are for running it directly.
# The image is the one in .github/docker/Dockerfile, which Dependabot keeps up to date.
set -e
cd "$(dirname "$0")"

: "${DBUSER:=dbuser}" "${DBPASSWORD:=secret}" "${DBDATABASE:=test_db}" "${DBPORT:=30000}"
container_id_pg=ci_postgis
pg_img="$(sed -n 's/^FROM[[:space:]]\{1,\}//p' .github/docker/Dockerfile)"
if [ -z "$pg_img" ]; then
	echo "no FROM line in .github/docker/Dockerfile" >&2
	exit 1
fi

case "$1" in
	"pull")
		docker pull "$pg_img"
		;;
	"stop")
		docker stop "$container_id_pg"
		docker rm "$container_id_pg"
		;;
	*)
		# a run that failed before teardown leaves the container behind
		docker rm -f "$container_id_pg" >/dev/null 2>&1 || true
		docker run \
			-e POSTGRES_PASSWORD="$DBPASSWORD" \
			-e POSTGRES_USER="$DBUSER" \
			-e POSTGRES_DB="$DBDATABASE" \
			-p "127.0.0.1:$DBPORT:5432/tcp" \
			--health-cmd='PGPASSWORD=$POSTGRES_PASSWORD psql \
			--user=$POSTGRES_USER --dbname=$POSTGRES_DB \
			--host=127.0.0.1 --quiet --no-align --tuples-only \
			-1 --command="SELECT postgis_version()"' \
			--health-interval 1s \
			--health-retries 60 \
			--health-start-period 2s \
			--health-timeout 2s \
			--name="$container_id_pg" \
			-d \
			"$pg_img"

		while [ "$(docker inspect -f \{\{.State.Health.Status\}\} $container_id_pg)" != "healthy" ]; do
			echo "waiting for container $container_id_pg start..."
			sleep 2
		done
		;;
esac
