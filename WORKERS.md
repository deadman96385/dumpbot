# Dump Worker System

This document describes the Redis-based dump worker system that processes firmware extraction jobs independently of Jenkins.

## Overview

The dump worker system provides a scalable, fault-tolerant alternative to Jenkins for processing firmware dumps. It uses Redis for job queuing and state management, allowing multiple workers to process dumps concurrently.

## Architecture

### Components

1. **Job Queue** (`message_queue.py`) - Redis-based job queue with priority handling
2. **Workers** (`dump_worker.py`) - Process dump jobs independently
3. **Handlers** (`handlers.py`) - Modified to queue jobs instead of calling Jenkins
4. **Storage** - Redis for job state, progress tracking, and coordination

### Job Flow

```
User Command → Validation → Job Queue → Worker → Processing → Completion
     ↓              ↓           ↓          ↓          ↓           ↓
  /dump URL    DumpArguments  Redis    Worker   Extraction   GitLab Push
                   ↓              ↓         ↓          ↓           ↓
              Job Creation    Job Storage  Process   Progress   Notification
```

## Features

### 🚀 **Full Feature Parity**
- **Download optimization** with Xiaomi mirrors, special URL handling
- **Dual extraction** methods (Python dumpyara + alternative dumper)
- **Comprehensive property extraction** with extensive fallback logic
- **Boot image processing** with device tree extraction
- **GitLab integration** with repository/subgroup creation
- **Cross-chat messaging** with status updates
- **Channel notifications** for whitelisted firmware

### 📊 **Enhanced Monitoring**
- Real-time progress tracking (10 steps with percentages)
- Job status commands (`/status` and `/status [job_id]`)
- Worker heartbeat monitoring
- Queue statistics and health monitoring

### 🛠 **Operational Benefits**
- **Non-blocking**: Bot remains responsive during dumps
- **Scalable**: Multiple workers can run simultaneously
- **Fault-tolerant**: Automatic job retry with exponential backoff
- **Resource isolation**: Workers use temporary directories
- **Graceful shutdown**: Workers handle interrupts properly

## Worker Management

### Starting Workers

```bash
# Start a single worker
python run_worker.py

# Start worker with custom ID
python run_worker.py worker_01

# Start multiple workers (in separate terminals)
python run_worker.py worker_01 &
python run_worker.py worker_02 &
python run_worker.py worker_03 &
```

### Production Deployment

For production environments, consider using process managers:

#### Option 1: systemd (Linux)

```ini
# /etc/systemd/system/dumpbot-worker@.service
[Unit]
Description=DumpBot Worker %i
After=network.target redis.service

[Service]
Type=simple
User=dumpbot
WorkingDirectory=/path/to/dumpbot
ExecStart=/usr/bin/python3 run_worker.py worker_%i
Restart=always
RestartSec=10
Environment=PYTHONPATH=/path/to/dumpbot

[Install]
WantedBy=multi-user.target
```

Start workers:
```bash
sudo systemctl enable dumpbot-worker@{1..3}
sudo systemctl start dumpbot-worker@{1..3}
```

#### Option 2: Docker Compose

```yaml
# docker-compose.yml
version: '3.8'
services:
  worker1:
    build: .
    command: python run_worker.py worker_01
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DUMPER_TOKEN=${DUMPER_TOKEN}
    depends_on:
      - redis
    restart: unless-stopped

  worker2:
    build: .
    command: python run_worker.py worker_02
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DUMPER_TOKEN=${DUMPER_TOKEN}
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:alpine
    restart: unless-stopped
```

### Monitoring Workers

#### Check Queue Status
```bash
# Overall queue status
/status

# Specific job status
/status abc123def
```

#### Redis CLI Monitoring
```bash
# Check active workers
redis-cli KEYS "dumpyarabot:worker:*"

# Check job queue length
redis-cli LLEN "dumpyarabot:job_queue"

# Monitor in real-time
redis-cli MONITOR
```

## Configuration

### Required Environment Variables

```bash
# Redis configuration
REDIS_URL=redis://localhost:6379/0
REDIS_KEY_PREFIX=dumpyarabot:

# GitLab integration
DUMPER_TOKEN=your_gitlab_token_here

# Telegram (for channel notifications)
API_KEY=your_telegram_bot_token

# Bot configuration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
ALLOWED_CHATS=[-1001234567890]
```

### Optional Configuration

```bash
# Worker behavior
WORKER_TIMEOUT=7200  # 2 hours max per job
MAX_RETRIES=3

# Download optimization
ENABLE_MIRRORS=true
DOWNLOAD_TIMEOUT=1800  # 30 minutes

# Processing options
DEFAULT_EXTRACT_METHOD=python  # or "alternative"
ENABLE_DEVICE_TREE_GEN=true
```

## Job Management

### Job States

- **QUEUED** - Job waiting for available worker
- **PROCESSING** - Job currently being processed
- **COMPLETED** - Job finished successfully
- **FAILED** - Job failed after max retries
- **CANCELLED** - Job cancelled by admin
- **RETRYING** - Job being retried after failure

### Commands

#### Queue a Dump Job
```bash
/dump https://example.com/firmware.zip [options]

# Options:
# a - Use alternative dumper
# f - Force (skip existing build check)
# p - Private dump (delete original message)
# b - Add to blacklist
```

#### Cancel a Job
```bash
/cancel abc123def    # Cancel worker job
/cancel jenkins_123  # Cancel Jenkins job (fallback)
```

#### Check Status
```bash
/status              # Queue overview
/status abc123def    # Specific job status
```

## Error Handling

### Automatic Retry Logic

Jobs automatically retry on failure with exponential backoff:
- **Retry 1**: 2 seconds delay
- **Retry 2**: 4 seconds delay
- **Retry 3**: 8 seconds delay
- **Max retries**: 3 attempts

### Common Error Scenarios

1. **Download failures**: Mirror optimization and tool fallbacks
2. **Extraction failures**: Dual extraction method support
3. **GitLab failures**: Detailed API error reporting
4. **Worker crashes**: Job requeue for other workers
5. **Network issues**: Configurable timeouts and retries

### Failure Analysis

The system includes Gemini AI-powered failure analysis (inherited from Jenkins integration):
- Automatic log analysis on job failures
- Detailed error categorization and suggestions
- Integration with existing AI analysis system

## Migration from Jenkins

The worker system provides backward compatibility:

1. **Parallel operation**: Can run alongside Jenkins
2. **Gradual migration**: Move workloads incrementally
3. **Fallback support**: Cancel commands try worker queue first, then Jenkins
4. **Command compatibility**: Same `/dump` command interface

### Migration Steps

1. **Phase 1**: Deploy workers, test with non-critical dumps
2. **Phase 2**: Route new dumps to workers, keep Jenkins for admin use
3. **Phase 3**: Full migration, Jenkins as emergency fallback only
4. **Phase 4**: Retire Jenkins integration

## Performance Characteristics

### Resource Usage

Each worker process:
- **Memory**: ~500MB baseline + firmware size (2-8GB peak)
- **CPU**: Variable based on extraction complexity
- **Disk**: Temporary storage only (auto-cleanup)
- **Network**: Download bandwidth dependent

### Throughput

- **Sequential processing**: 1 job per worker
- **Parallel capacity**: Limited by system resources
- **Typical job time**: 10-45 minutes depending on firmware size
- **Queue latency**: Near-instantaneous job pickup

### Scaling Guidelines

- **Small deployment**: 1-2 workers, 4GB RAM minimum
- **Medium deployment**: 3-5 workers, 16GB RAM recommended
- **Large deployment**: 5+ workers, 32GB+ RAM, SSD storage
- **Redis**: Minimal resource requirements, can be shared

## Troubleshooting

### Common Issues

#### Workers not processing jobs
```bash
# Check Redis connectivity
redis-cli ping

# Check worker logs
tail -f worker.log

# Verify queue has jobs
redis-cli LLEN "dumpyarabot:job_queue"
```

#### Jobs stuck in processing
```bash
# Check worker heartbeats
redis-cli KEYS "dumpyarabot:worker:*"

# Manual job cleanup (if worker crashed)
redis-cli DEL "dumpyarabot:worker:worker_01"
```

#### GitLab integration failures
```bash
# Test GitLab connectivity
curl -H "Authorization: Bearer $DUMPER_TOKEN" https://dumps.tadiphone.dev/api/v4/user

# Check token permissions
# Token needs: api, read_repository, write_repository
```

### Debug Mode

Enable detailed logging:
```bash
export PYTHONPATH=/path/to/dumpbot
export DEBUG=1
python run_worker.py debug_worker
```

### Log Analysis

Worker logs include:
- Job assignment and progress
- Download mirror selection
- Extraction method decisions
- GitLab API interactions
- Error details with stack traces

## Security Considerations

### Access Control
- Workers inherit bot's GitLab permissions
- Jobs run with worker process permissions
- Temporary files isolated per job
- No credential storage in job data

### Network Security
- Redis should be on private network
- GitLab API over HTTPS only
- Download URL validation
- Whitelist-based channel publishing

### Resource Limits
- Temporary directory cleanup
- Process memory limits (if configured)
- Download timeouts to prevent hang
- Maximum job execution time

## Future Enhancements

### Planned Features
- [ ] Web dashboard for queue monitoring
- [ ] Metrics collection (Prometheus/Grafana)
- [ ] Priority queue for urgent dumps
- [ ] Distributed storage for large files
- [ ] Advanced scheduling (time-based, resource-aware)

### Integration Opportunities
- [ ] GitHub Actions for CI/CD testing
- [ ] Slack/Discord notifications
- [ ] Webhook system for external integrations
- [ ] API for programmatic job submission

---

## Quick Start

1. **Install dependencies**: `uv sync`
2. **Configure Redis**: Set `REDIS_URL` in environment
3. **Set GitLab token**: Export `DUMPER_TOKEN`
4. **Start worker**: `python run_worker.py`
5. **Test dump**: `/dump https://example.com/firmware.zip`
6. **Monitor progress**: `/status`

The worker system provides a robust, scalable foundation for firmware processing that can grow with your needs while maintaining the full feature set of the original Jenkins implementation.