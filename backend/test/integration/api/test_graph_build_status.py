import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_file_graph_build_status_counts_only_current_pending_chunks(
    test_client, admin_headers, knowledge_base_resource, postgres_sessions
):
    """真实 HTTP 和 PG 验证文件、代次和图谱向量阶段的范围。"""
    from uuid import uuid4

    from sqlalchemy import select

    from yuxi.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeFile
    from yuxi.shared.datetime import utc_now

    kb_id = knowledge_base_resource["kb_id"]
    other_kb, target, other, foreign, folder, deleted = [uuid4().hex for _ in range(6)]
    async with postgres_sessions() as session:
        session.add(KnowledgeBase(kb_id=other_kb, name=other_kb, kb_type="milvus"))
        await session.flush()
        session.add_all(
            [
                KnowledgeFile(kb_id=kb_id, file_id=target, filename="target", active_generation=2),
                KnowledgeFile(kb_id=kb_id, file_id=other, filename="other"),
                KnowledgeFile(kb_id=other_kb, file_id=foreign, filename="foreign"),
                KnowledgeFile(kb_id=kb_id, file_id=folder, filename="folder", is_folder=True),
                KnowledgeFile(kb_id=kb_id, file_id=deleted, filename="deleted", deleted_at=utc_now()),
            ]
        )
        await session.flush()
        for file_id, generation, indexed, structured, index in [
            (target, 2, False, False, 0),
            (target, 2, False, True, 1),
            (target, 2, True, True, 2),
            (target, 1, False, False, 3),
            (other, 1, False, False, 0),
        ]:
            session.add(
                KnowledgeChunk(
                    chunk_id=uuid4().hex,
                    kb_id=kb_id,
                    file_id=file_id,
                    chunk_index=index,
                    generation=generation,
                    content="test",
                    graph_indexed=indexed,
                    graph_structure_indexed=structured,
                )
            )
        await session.commit()
    base = f"/api/knowledge/knowledge-bases/{kb_id}/graph-build/files"
    try:
        response = await test_client.get(f"{base}/{target}/status", headers=admin_headers)
        assert response.status_code == 200 and response.json() == {"pending_chunks": 2}, response.text
        assert (await test_client.get(f"{base}/{target}/status")).status_code in {401, 403}
        for file_id, expected in [(foreign, 404), (deleted, 404), (uuid4().hex, 404), (folder, 400)]:
            response = await test_client.get(f"{base}/{file_id}/status", headers=admin_headers)
            assert response.status_code == expected, response.text
        async with postgres_sessions() as session:
            file = await session.scalar(select(KnowledgeFile).where(KnowledgeFile.file_id == target))
            file.active_generation = 3
            await session.commit()
        response = await test_client.get(f"{base}/{target}/status", headers=admin_headers)
        assert response.status_code == 200 and response.json() == {"pending_chunks": 0}, response.text
    finally:
        async with postgres_sessions() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == other_kb))
            await session.delete(kb)
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_build_status_and_failed_chunk_samples(test_client, admin_headers, knowledge_base_resource):
    kb_id = knowledge_base_resource["kb_id"]

    status_response = await test_client.get(
        f"/api/knowledge/knowledge-bases/{kb_id}/graph-build/status",
        headers=admin_headers,
    )
    samples_response = await test_client.get(
        f"/api/knowledge/knowledge-bases/{kb_id}/graph-build/failed-chunks?limit=10",
        headers=admin_headers,
    )

    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["extraction_counts"] == {
        "pending": 0,
        "succeeded": 0,
        "failed": 0,
    }
    assert samples_response.status_code == 200, samples_response.text
    assert samples_response.json() == {"kb_id": kb_id, "samples": []}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_build_rejections_do_not_create_jobs(test_client, admin_headers, knowledge_base_resource, postgres_sessions):
    """真实 HTTP 拒绝未锁配置和非法范围，独立 PG 连接确认没有执行意图。"""
    from sqlalchemy import select

    from yuxi.modules.background_jobs.models import BackgroundJobRecord
    from yuxi.modules.knowledge.graphs.service import GRAPH_TASK_TYPE

    kb_id = knowledge_base_resource["kb_id"]
    base = f"/api/knowledge/knowledge-bases/{kb_id}/graph-build"
    for path, body, detail in [
        ("index", None, "请先确认并锁定图谱抽取配置"),
        ("reconcile", {"mode": "invalid"}, "mode 必须是 failed 或 all_vectors"),
    ]:
        response = await test_client.post(f"{base}/{path}", json=body, headers=admin_headers)
        assert response.status_code == 400 and response.json() == {"detail": detail}, response.text
    async with postgres_sessions() as observer:
        assert (
            await observer.scalar(
                select(BackgroundJobRecord.id).where(
                    BackgroundJobRecord.type == GRAPH_TASK_TYPE, BackgroundJobRecord.payload["kb_id"].as_string() == kb_id
                )
            )
            is None
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_active_graph_job_blocks_requests_without_resetting(test_client, admin_headers, knowledge_base_resource, postgres_sessions):
    """已执行且租约有效的任务阻止重复提交和重置，现有配置与任务事实保持。"""
    from datetime import timedelta
    from uuid import uuid4

    from sqlalchemy import select

    from yuxi.modules.background_jobs.models import BackgroundJobRecord
    from yuxi.modules.knowledge.graphs.service import GRAPH_TASK_TYPE
    from yuxi.modules.knowledge.models import KnowledgeBase
    from yuxi.shared.datetime import utc_now

    kb_id = knowledge_base_resource["kb_id"]
    job_id = uuid4().hex
    async with postgres_sessions() as writer:
        row = await writer.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
        params = row.additional_params
        writer.add(
            BackgroundJobRecord(
                id=job_id,
                name="pytest graph active owner",
                type=GRAPH_TASK_TYPE,
                payload={"kb_id": kb_id, "action": "build"},
                status="running",
                worker_id="pytest-owner",
                started_at=utc_now(),
                heartbeat_at=utc_now(),
                lease_expires_at=utc_now() + timedelta(minutes=10),
            )
        )
        await writer.commit()
    try:
        base = f"/api/knowledge/knowledge-bases/{kb_id}/graph-build"
        for action in ["index", "reconcile", "reset"]:
            response = await test_client.post(f"{base}/{action}", json={}, headers=admin_headers)
            expected = "该知识库存在正在运行的图谱构建任务，无法重置" if action == "reset" else "该知识库已有正在运行的图谱构建任务"
            assert response.status_code == 409 and response.json() == {"detail": expected}, response.text
        async with postgres_sessions() as observer:
            jobs = list(
                await observer.scalars(select(BackgroundJobRecord).where(BackgroundJobRecord.payload["kb_id"].as_string() == kb_id))
            )
            assert [(job.id, job.status, job.payload) for job in jobs] == [(job_id, "running", {"kb_id": kb_id, "action": "build"})]
            row = await observer.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            assert row.additional_params == params
    finally:
        async with postgres_sessions() as writer:
            job = await writer.get(BackgroundJobRecord, job_id)
            await writer.delete(job)
            await writer.commit()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["build", "reconcile"])
async def test_graph_request_records_payload_and_worker_consumes_once(
    test_client, admin_headers, knowledge_base_resource, postgres_sessions, action
):
    """空知识库走正式提交与 worker，回读唯一任务、原 payload 和执行结果，不调用外部抽取模型。"""
    import asyncio

    from sqlalchemy import select

    from yuxi.modules.background_jobs.models import BackgroundJobRecord

    kb_id = knowledge_base_resource["kb_id"]
    base = f"/api/knowledge/knowledge-bases/{kb_id}/graph-build"
    configured = await test_client.post(
        f"{base}/config", json={"extractor_type": "llm", "extractor_options": {"model_spec": "unused/empty-graph"}}, headers=admin_headers
    )
    assert configured.status_code == 200, configured.text
    response = await test_client.post(f"{base}/{'index' if action == 'build' else 'reconcile'}", json={}, headers=admin_headers)
    assert response.status_code == 200 and response.json()["status"] == "queued", response.text
    payload = {"kb_id": kb_id, "action": action}
    if action == "reconcile":
        payload["reconcile_mode"] = "failed"
        assert response.json()["mode"] == "failed"
    for _ in range(100):
        async with postgres_sessions() as observer:
            jobs = list(
                await observer.scalars(select(BackgroundJobRecord).where(BackgroundJobRecord.payload["kb_id"].as_string() == kb_id))
            )
            assert len(jobs) == 1
            job = jobs[0]
            assert job.id == response.json()["job_id"] and job.payload == payload
            if job.status in {"success", "failed", "cancelled"}:
                assert job.status == "success", job.error
                assert job.attempt_count == 1 and job.result["kb_id"] == kb_id
                assert job.result["success"] == 0 and job.result["extraction_failed"] == 0
                break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("图谱任务未在限时内结束")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_file_graph_build_validates_scope_and_persists_generation(
    test_client, admin_headers, knowledge_base_resource, postgres_sessions
):
    """非法文件不产生任务；合法文件的当前代次随任务持久化并交给 worker。"""
    import asyncio
    from uuid import uuid4

    from sqlalchemy import delete, select

    from yuxi.modules.background_jobs.models import BackgroundJobRecord
    from yuxi.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeFile

    kb_id = knowledge_base_resource["kb_id"]
    other_kb, target, empty, folder, foreign = [uuid4().hex for _ in range(5)]
    async with postgres_sessions() as session:
        session.add(KnowledgeBase(kb_id=other_kb, name=other_kb, kb_type="milvus"))
        await session.flush()
        session.add_all(
            [
                KnowledgeFile(kb_id=kb_id, file_id=target, filename="target", active_generation=2),
                KnowledgeFile(kb_id=kb_id, file_id=empty, filename="empty"),
                KnowledgeFile(kb_id=kb_id, file_id=folder, filename="folder", is_folder=True),
                KnowledgeFile(kb_id=other_kb, file_id=foreign, filename="foreign"),
            ]
        )
        await session.flush()
        session.add(
            KnowledgeChunk(
                chunk_id=uuid4().hex,
                kb_id=kb_id,
                file_id=target,
                chunk_index=0,
                generation=2,
                content="已索引",
                graph_structure_indexed=True,
                graph_indexed=True,
            )
        )
        await session.commit()
    base = f"/api/knowledge/knowledge-bases/{kb_id}/graph-build"
    try:
        configured = await test_client.post(
            f"{base}/config",
            json={"extractor_type": "llm", "extractor_options": {"model_spec": "unused/empty-graph"}},
            headers=admin_headers,
        )
        assert configured.status_code == 200, configured.text
        for file_id, status in [
            (foreign, 404),
            (uuid4().hex, 404),
            (folder, 400),
            (empty, 400),
            (None, 400),
            ("", 400),
            ("  ", 400),
            (123, 400),
            (False, 400),
            ([], 400),
        ]:
            response = await test_client.post(f"{base}/index", json={"file_id": file_id}, headers=admin_headers)
            assert response.status_code == status, response.text
        async with postgres_sessions() as observer:
            assert not (
                await observer.scalars(select(BackgroundJobRecord).where(BackgroundJobRecord.payload["kb_id"].as_string() == kb_id))
            ).all()
        response = await test_client.post(f"{base}/index", json={"file_id": target}, headers=admin_headers)
        assert response.status_code == 200, response.text
        for _ in range(100):
            async with postgres_sessions() as observer:
                job = await observer.get(BackgroundJobRecord, response.json()["job_id"])
                assert job.payload == {"kb_id": kb_id, "action": "build", "file_id": target, "generation": 2}
                if job.status in {"success", "failed", "cancelled"}:
                    assert job.status == "success", job.error
                    assert job.result["remaining"] == 0
                    break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("单文件图谱任务未在限时内结束")
    finally:
        for _ in range(100):
            async with postgres_sessions() as session:
                jobs = list(
                    await session.scalars(select(BackgroundJobRecord).where(BackgroundJobRecord.payload["kb_id"].as_string() == kb_id))
                )
                if all(job.status in {"success", "failed", "cancelled"} for job in jobs):
                    await session.execute(delete(BackgroundJobRecord).where(BackgroundJobRecord.payload["kb_id"].as_string() == kb_id))
                    await session.commit()
                    break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("测试作业仍在执行，不能清理其数据")
        async with postgres_sessions() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == other_kb))
            await session.delete(kb)
            await session.commit()
