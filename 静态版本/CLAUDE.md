# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PKUAutoElective is an automated course selection tool for Peking University's elective system during the add/drop period. This repository contains a hybrid of two versions:

- **PKUAutoElective2023**: Uses TensorFlow-based CNN+GRU+CTC neural network for CAPTCHA recognition
- **PKUAutoElective v6.0.0**: Uses PyTorch-based CNN model for CAPTCHA recognition (discontinued as of 2021.03.12)

Both versions automatically select courses based on user-defined rules with high CAPTCHA recognition accuracy.

## Development Commands

### Install Dependencies

**For TensorFlow version (current):**
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**For PyTorch version (legacy):**
```bash
# Install non-PyTorch dependencies first
pip install requests lxml Pillow opencv-python numpy flask -i https://pypi.tuna.tsinghua.edu.cn/simple

# Install PyTorch (CPU version)
pip install torch==1.8.0+cpu -f https://download.pytorch.org/whl/torch_stable.html
```

### Run the Main Application
```bash
python main.py
# Or with config file:
python main.py -c config.ini
# With monitor enabled:
python main.py -m
```

### Test CAPTCHA Recognition

**TensorFlow version:**
```bash
cd test/
python test_captcha_recognizer.py
```

**PyTorch version:**
```bash
cd test/
python test_cnn.py
```

### Bootstrap Mode (Self-training)
```bash
python bootstrap.py
```

## Architecture

### Core Components
- **autoelective/**: Main package containing all functionality
  - **client.py**: HTTP client for elective system communication
  - **elective.py**: Core elective system interaction logic
  - **iaaa.py**: IAAA authentication system handler
  - **cli.py**: Command-line interface and argument parsing
  - **loop.py**: Main event loops for IAAA login and elective operations
  - **monitor.py**: Web monitoring interface
  - **captcha/**: CAPTCHA recognition using TensorFlow CNN+GRU+CTC model
  - **config.py**: Configuration management

### Key Flow
1. **Authentication**: Login through IAAA system using credentials
2. **Session Management**: Maintain multiple client sessions (max 5 per IP)
3. **Course Monitoring**: Poll elective system for available courses
4. **CAPTCHA Solving**: Use trained model for real-time recognition
5. **Rule Processing**: Apply mutex/delay rules for course selection
6. **Automatic Selection**: Submit course selection requests when conditions are met

## Configuration

### Main Config (config.ini)
- Copy `config.sample.ini` to `config.ini` and configure:
  - **[user]**: Student credentials and account type (dual_degree support)
  - **[client]**: Refresh intervals, timeouts, session management
  - **[monitor]**: Web interface settings (optional)
  - **[course:id]**: Course definitions (name, class, school)
  - **[mutex:id]**: Mutually exclusive course rules
  - **[delay:id]**: Delay rules based on remaining capacity

### CAPTCHA Models

**TensorFlow version (current):**
- Model: `recognizer_v11-CNN5-GRU-H128-CTC-C1`
- Architecture: CNN5 + GRU + CTC for variable-length recognition
- Performance: 98% accuracy, 10-30ms per recognition on CPU

**PyTorch version (legacy):**
- Architecture: CNN model
- Performance: 99.16% accuracy
- Model files: Stored in captcha recognition module

## Important Notes

### Version Differences
This repository contains elements from two different versions:
- **Current (TensorFlow)**: Active development, uses tensorflow==2.12.0
- **Legacy (PyTorch)**: Discontinued as of 2021.03.12, uses PyTorch 1.8.0+

When working with the code, check dependencies in `requirements.txt` to determine which version is being used.

### Rate Limiting
- Minimum refresh interval: 4 seconds (to avoid server pressure)
- IP-level rate limiting exists on the elective system
- Multiple client sessions are managed automatically (max 5)

### Threading Architecture
- **IAAA Thread**: Handles authentication and login loops
- **Elective Thread**: Main course monitoring and selection logic  
- **Monitor Thread**: Optional web interface for status monitoring

### Security Considerations
- Never commit credentials to the repository
- The tool is designed for defensive/legitimate use only
- Respects server rate limits to avoid being blocked

## File Structure
- **main.py**: Entry point, delegates to CLI
- **bootstrap.py**: Self-training mode for CAPTCHA recognition
- **test/**: Contains CAPTCHA recognition tests
  - `test_captcha_recognizer.py`: TensorFlow version tests
  - `test_cnn.py`: PyTorch version tests (if available)
- **autoelective/captcha/model/**: Complete CAPTCHA training framework (TensorFlow)

## Advanced Features

### Multi-Process Course Selection
- Support for multiple accounts with separate config files
- Session management across processes (max 5 sessions per IP total)
- Different page monitoring via separate configurations

### Custom Course Selection Rules
- **Mutex Rules**: Mutually exclusive courses (select only one from a group)
- **Delay Rules**: Trigger selection only when remaining spots ≤ threshold
- Priority-based selection when multiple courses become available simultaneously

### Monitoring Interface
- Optional web interface via `-m` flag
- HTTP endpoints for status monitoring:
  - `GET /` or `/rules`: View routing rules
  - `GET /stat/course`: Course-related status
  - `GET /stat/error`: Error-related status
  - `GET /stat/loop`: Loop thread status
- Suitable for server deployment with nginx reverse proxy

### User-Agent Customization
- Default pool in `user_agents.txt.gz`
- Custom pool via `user_agents.user.txt`
- Random selection per IAAA login session