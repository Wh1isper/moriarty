from __future__ import annotations

import os
from functools import cached_property

import redis.asyncio as redis
from fastapi import Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from moriarty.log import logger
from moriarty.matrix.connector.invoker import get_bridge_name
from moriarty.matrix.envs import get_bridge_result_queue_url
from moriarty.matrix.job_manager.bridge_wrapper import BridgeWrapper, get_bridge_wrapper
from moriarty.matrix.job_manager.params import InferenceJob, InferenceResult
from moriarty.matrix.operator_.autoscaler import (
    AutoscalerManager,
    get_autoscaler_manager,
)
from moriarty.matrix.operator_.dbutils import get_db_session
from moriarty.matrix.operator_.orm import AutoscalerORM, EndpointORM, InferenceLogORM
from moriarty.matrix.operator_.rds import get_redis_client
from moriarty.matrix.operator_.spawner import plugin
from moriarty.matrix.operator_.spawner.manager import get_spawner
from moriarty.sidecar.params import MatrixCallback
from moriarty.sidecar.producer import JobProducer


class EndpointMixin:
    session: AsyncSession

    async def get_endpoint_orm(self, endpoint_name: str) -> EndpointORM | None:
        return (
            await self.session.execute(
                select(EndpointORM).where(EndpointORM.endpoint_name == endpoint_name)
            )
        ).scalar_one_or_none()

    async def get_avaliable_endpoints(self) -> list[str]:
        endpoint_names = (
            (
                await self.session.execute(
                    select(EndpointORM.endpoint_name).where(EndpointORM.available == True)
                )
            )
            .scalars()
            .all()
        )
        return endpoint_names


def get_bridger(
    bridge_name: str = Depends(get_bridge_name),
    bridge_wrapper: BridgeWrapper = Depends(get_bridge_wrapper),
    redis_client: redis.Redis | redis.RedisCluster = Depends(get_redis_client),
    session: AsyncSession = Depends(get_db_session),
    bridge_result_queue_url: str = Depends(get_bridge_result_queue_url),
) -> Bridger:
    return Bridger(
        bridge_name=bridge_name,
        bridge_wrapper=bridge_wrapper,
        redis_client=redis_client,
        session=session,
        bridge_result_queue_url=bridge_result_queue_url,
    )


async def get_operaotr(
    spawner: plugin.Spawner = Depends(get_spawner),
    bridger: Bridger = Depends(get_bridger),
    session: AsyncSession = Depends(get_db_session),
    redis_client: redis.Redis | redis.RedisCluster = Depends(get_redis_client),
    autoscaler_manager: AutoscalerManager = Depends(get_autoscaler_manager),
) -> Operator:
    return Operator(
        spawner=spawner,
        bridger=bridger,
        session=session,
        redis_client=redis_client,
        autoscaler_manager=autoscaler_manager,
    )


class Bridger(EndpointMixin):
    def __init__(
        self,
        bridge_name: str,
        bridge_wrapper: BridgeWrapper,
        redis_client: redis.Redis | redis.RedisCluster,
        session: AsyncSession,
        bridge_result_queue_url: None | str = None,
    ) -> None:
        self.bridge_name = bridge_name
        self.bridge_wrapper = bridge_wrapper
        self.redis_client = redis_client
        self.session = session
        self.bridge_result_queue_url = bridge_result_queue_url

    @cached_property
    def job_producer(self) -> JobProducer:
        return JobProducer(redis_client=self.redis_client)

    async def bridge_all(self) -> None:
        for endpoint_name in await self.get_avaliable_endpoints():
            await self.bridge_one(endpoint_name)

    async def has_capacity(self, endpoint_name: str) -> bool:
        endpoint_orm = await self.get_endpoint_orm(endpoint_name)
        if endpoint_orm is None:
            logger.warning(f"Endpoint not found: {endpoint_name}, may be deleted?")
            return False

        unfinished_count = await self.job_producer.count_unfinished_jobs(endpoint_name)
        return unfinished_count < endpoint_orm.queue_capacity

    async def bridge_one(self, endpoint_name: str) -> None:
        async def _warp_produce_job(job: InferenceJob) -> None:
            await self.job_producer.invoke(
                endpoint_name,
                params=job.payload,
            )
            log_orm = InferenceLogORM(
                inference_id=job.inference_id,
                endpoint_name=endpoint_name,
                inference_job=job.model_dump(),
            )
            self.session.add(log_orm)
            await self.session.commit()

        logger.info(f"Bridge endpoint: {endpoint_name}")
        while await self.has_capacity(endpoint_name):
            sampled_count = await self.bridge_wrapper.sample_job(
                bridge=self.bridge_name,
                endpoint_name=endpoint_name,
                process_func=_warp_produce_job,
            )
            if not sampled_count:
                return
            logger.debug(f"One job sampled -> {endpoint_name}")

    async def bridge_result(self, callback: MatrixCallback) -> None:
        await self.bridge_wrapper.enqueue_result(
            bridge=self.bridge_name,
            bridge_result_queue_url=self.bridge_result_queue_url,
            result=InferenceResult.from_proxy_callback(callback),
        )


class Operator:
    def __init__(
        self,
        spawner: plugin.Spawner,
        bridger: Bridger,
        session: AsyncSession,
        redis_client: redis.Redis | redis.RedisCluster,
        autoscaler_manager: AutoscalerManager,
    ) -> None:
        self.spawner = spawner
        self.bridger = bridger
        self.session = session
        self.redis_client = redis_client
        self.autoscaler_manager = autoscaler_manager

    async def handle_callback(self, callback: MatrixCallback) -> None:
        await self.bridger.bridge_result(callback)
        await self.session.execute(
            update(InferenceLogORM)
            .where(InferenceLogORM.inference_id == callback.inference_id)
            .values(
                status=callback.status,
                callback_response=callback.model_dump(),
                finished_at=func.now(),
            )
        )
        await self.session.commit()
        logger.info(f"Callback handled: {callback}")
