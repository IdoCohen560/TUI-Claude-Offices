.PHONY: install dev backend tui simulate test-agent lint fmt test typecheck \
	hooks-install hooks-uninstall hooks-reinstall hooks-status hooks-logs hooks-logs-follow hooks-logs-clear \
	hooks-debug-on hooks-debug-off clean clean-db clean-all

install:
	cd backend && uv sync
	cd tui && uv sync
	cd hooks && uv sync

dev:
	@echo "Starting backend and TUI..."
	@echo "1. Run 'make backend' in one terminal"
	@echo "2. Run 'make tui' in another terminal"

backend:
	make -C backend dev

tui:
	cd tui && uv run python office.py

simulate:
	uv run python scripts/simulate_events.py

test-agent:
	uv run python scripts/test_single_agent.py

lint:
	make -C backend lint

fmt:
	make -C backend fmt

test:
	make -C backend test

typecheck:
	make -C backend typecheck

# Hook management targets
hooks-install:
	cd hooks && ./install.sh

hooks-uninstall:
	cd hooks && ./uninstall.sh

hooks-reinstall: hooks-uninstall hooks-install
	@echo "Hooks reinstalled"

hooks-status:
	@echo "=== Installed Claude Code Hooks ==="
	@cat ~/.claude/settings.json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin).get('hooks',{}); [print(f'  {k}: {len(v)} hook(s)') for k,v in d.items()]" 2>/dev/null || echo "  No hooks configured"
	@echo ""
	@echo "=== Hook Config ==="
	@cat ~/.claude/claude-office-config.env 2>/dev/null || echo "  No config file found"

hooks-logs:
	@echo "=== Recent Hook Logs ==="
	@tail -100 ~/.claude/claude-office-hooks.log 2>/dev/null || echo "  No log file found"

hooks-logs-follow:
	@tail -f ~/.claude/claude-office-hooks.log

hooks-logs-clear:
	@rm -f ~/.claude/claude-office-hooks.log
	@echo "Hook logs cleared"

hooks-debug-on:
	@sed -i 's/CLAUDE_OFFICE_DEBUG=0/CLAUDE_OFFICE_DEBUG=1/' ~/.claude/claude-office-config.env 2>/dev/null || true
	@grep -q "CLAUDE_OFFICE_DEBUG" ~/.claude/claude-office-config.env || echo "CLAUDE_OFFICE_DEBUG=1" >> ~/.claude/claude-office-config.env
	@echo "Hook debug logging enabled"

hooks-debug-off:
	@sed -i 's/CLAUDE_OFFICE_DEBUG=1/CLAUDE_OFFICE_DEBUG=0/' ~/.claude/claude-office-config.env 2>/dev/null || true
	@echo "Hook debug logging disabled"

# Cleanup targets
clean-db:
	rm -f backend/visualizer.db
	@echo "Database removed"

clean:
	@echo "Clean complete"

clean-all: clean clean-db hooks-logs-clear
	@echo "All build artifacts and data cleaned"
