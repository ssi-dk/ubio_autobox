# Contributing to ubio_autobox

Thank you for your interest in contributing to ubio_autobox! This document provides guidelines and information for contributors.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally
3. Set up the development environment using Pixi
4. Create a new branch for your feature or bugfix

## Development Setup

### Prerequisites
- [Pixi](https://pixi.sh/) for environment management
- Docker (for Bactopia execution)

### Environment Setup
```bash
# Clone the repository
git clone https://github.com/ssi-dk/ubio_autobox.git
cd ubio_autobox

# Set up environment with Pixi
pixi install
pixi shell

# Install in development mode
pip install -e ".[dev]"
```

## Making Changes

### Code Style
- Follow PEP 8 Python style guidelines
- Use meaningful variable and function names
- Add docstrings to all functions and classes
- Keep line length under 79 characters where possible

### Testing
- Write tests for new functionality
- Ensure all existing tests pass
- Run tests with: `pytest ubio_autobox_tests`

### Commit Messages
Use clear, descriptive commit messages:
```
Add feature: brief description

- Detailed explanation of changes
- Why the change was made
- Any breaking changes
```

## Submitting Changes

### Pull Request Process
1. Ensure your code follows the style guidelines
2. Add or update tests as needed
3. Update documentation if necessary
4. Submit a pull request with:
   - Clear description of changes
   - Reference to any related issues
   - Screenshots if UI changes are involved

### Pull Request Requirements
- [ ] Code follows project style guidelines
- [ ] Tests pass locally
- [ ] Documentation is updated
- [ ] Commit messages are clear
- [ ] No merge conflicts

## Reporting Issues

When reporting bugs or requesting features:

1. Check if the issue already exists
2. Use the issue templates if available
3. Provide detailed information:
   - Steps to reproduce (for bugs)
   - Expected vs actual behavior
   - Environment details (OS, Python version, etc.)
   - Relevant logs or error messages

## Code of Conduct

### Our Standards
- Be respectful and inclusive
- Accept constructive criticism gracefully
- Focus on what's best for the community
- Show empathy towards other contributors

### Unacceptable Behavior
- Harassment or discriminatory language
- Personal attacks or trolling
- Public or private harassment
- Publishing others' private information

## Development Guidelines

### Adding New Assets
When adding new Dagster assets:
1. Follow the existing naming conventions
2. Add appropriate metadata and descriptions
3. Include proper error handling
4. Add tests for the new functionality

### Database Changes
When modifying the DuckDB schema:
1. Ensure backward compatibility where possible
2. Add migration logic if needed
3. Update documentation
4. Test with existing data

### Dependencies
When adding new dependencies:
1. Add to `pixi.toml` for conda packages
2. Add to `pyproject.toml` for pip-only packages
3. Justify the need for new dependencies
4. Consider the impact on the environment size

## Getting Help

- Check the README.md for basic usage
- Look at existing code for examples
- Ask questions in issues or discussions
- Contact maintainers if needed

## Recognition

Contributors will be recognized in:
- The project's contributor list
- Release notes for significant contributions
- Documentation credits where appropriate

Thank you for contributing to ubio_autobox!
