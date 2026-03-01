# SKJ System - 选课系统

基于 PKUAutoElective 的自动选课系统，支持多配置并行运行和IP池轮换。

## 项目结构

- `静态版本/` - 使用 TensorFlow 的静态版本（当前使用）
- `动态版本/` - 使用 PyTorch 的动态版本（已弃用）
- `config1.ini` - 配置文件示例
- `run_static_multi.sh` - 多配置并行运行脚本
- `run_static.sh` - 单配置运行脚本
- `rotate_snat_cron.sh` - IP轮换脚本
- `rotate_snat.py` - IP轮换Python脚本
- `rotate_snat.env` - IP轮换配置文件
- `eip_pools.env` - IP池配置文件

## 主要功能

1. **自动选课** - 基于配置文件的自动选课功能
2. **多配置并行** - 支持同时运行多个配置文件
3. **IP轮换** - 支持腾讯云NAT网关的IP轮换功能
4. **验证码识别** - 使用 TensorFlow CNN+GRU+CTC 模型识别验证码

## 快速开始

### 1. 安装依赖

```bash
cd 静态版本
pip3 install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. 配置IP池（可选）

编辑 `rotate_snat.env` 文件，配置：
- `REGION` - 腾讯云区域
- `NAT_ID` - NAT网关ID
- `SUBNET_ID` - 子网ID
- `EIPS` - 弹性IP列表（逗号分隔）

编辑 `eip_pools.env` 文件，配置IP池：
- `POOL_A` - IP池A
- `POOL_B` - IP池B

### 3. 配置选课信息

编辑 `config1.ini` 文件，配置：
- 学号和密码
- 课程信息
- 刷新间隔等参数

### 4. 运行

单配置运行：
```bash
bash run_static.sh
```

多配置并行运行：
```bash
bash run_static_multi.sh /home/ubuntu/skj_system/config1.ini
```

## 配置说明

### 配置文件路径修复

所有脚本中的路径已从 `/home/ubuntu/work/skj` 更新为 `/home/ubuntu/skj_system`，包括：
- `run_static_multi.sh`
- `run_static.sh`
- `run_static_inspect.sh`
- `rotate_snat_cron.sh`
- `set_eip_pool.sh`
- `switch_eip_pool_hourly.sh`
- `rotate_snat.env`
- `静态版本/autoelective/loop.py`
- `静态版本/autoelective/logger.py`

### 虚拟环境

如果虚拟环境不存在，脚本会自动使用系统Python。建议创建虚拟环境：
```bash
python3 -m venv .venv-static
source .venv-static/bin/activate
pip install -r 静态版本/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 日志文件

- 多配置运行日志：`静态版本/log/multi/*.log`
- 错误日志：`静态版本/log/error/*/loop.error.log`
- PID文件：`静态版本/log/multi/pids/*.pid`

查看日志：
```bash
tail -f 静态版本/log/multi/config1.log
```

## IP轮换功能

系统支持自动IP轮换，通过腾讯云NAT网关实现。配置好 `rotate_snat.env` 后，系统会在每次循环结束时自动轮换IP。

## 注意事项

1. 不要使用过低的刷新间隔，建议不小于4秒
2. 选课网存在IP级别的限流，访问过于频繁可能导致IP被封禁
3. 确保IP池配置正确，否则IP轮换功能无法正常工作
4. 首次运行前需要配置好所有必要的参数

## 版本信息

- 基于 PKUAutoElective2023
- 验证码识别：TensorFlow CNN+GRU+CTC
- Python版本：3.10+
- TensorFlow版本：2.12.0

## 更新日志

### 2026-03-01
- 修复所有脚本中的路径问题（从 `/home/ubuntu/work/skj` 更新为 `/home/ubuntu/skj_system`）
- 修复虚拟环境检测逻辑，支持系统Python回退
- 清空IP池配置，等待重新配置
- 修复Flask和Werkzeug版本兼容性问题
