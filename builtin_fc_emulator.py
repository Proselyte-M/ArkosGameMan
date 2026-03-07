from __future__ import annotations

import os
import sys
import time
from importlib import import_module
from typing import Any

pygame: Any | None = None
try:
    pygame = import_module("pygame")
except Exception:
    pygame = None


class MiniFC:
    def __init__(self) -> None:
        self.a = 0
        self.x = 0
        self.y = 0
        self.sp = 0xFF
        self.pc = 0x8000
        self.status = 0
        self.mem = [0] * 0x10000
        self.screen_width = 256
        self.screen_height = 240
        self.screen = None
        self.clock = pygame.time.Clock() if pygame else None

    def load_rom(self, rom_path: str) -> None:
        with open(rom_path, "rb") as f:
            rom_data = f.read()
        if len(rom_data) < 16:
            raise ValueError("无效的 .nes ROM 文件（文件头缺失）")
        rom_prg = rom_data[16:]
        for i, byte in enumerate(rom_prg):
            pos = 0x8000 + i
            if pos < 0x10000:
                self.mem[pos] = byte
        print(f"加载 ROM 成功，大小: {len(rom_prg)} 字节")

    def cpu_step(self) -> None:
        op = self.mem[self.pc]
        self.pc += 1
        if op == 0xA9:
            self.a = self.mem[self.pc]
            self.pc += 1
            return
        if op == 0x8D:
            addr = self.mem[self.pc] | (self.mem[self.pc + 1] << 8)
            self.mem[addr] = self.a
            self.pc += 2
            return
        if op == 0x4C:
            addr = self.mem[self.pc] | (self.mem[self.pc + 1] << 8)
            self.pc = addr
            return
        if op == 0x00:
            raise StopIteration("CPU 执行中断")

    def run(self) -> None:
        if pygame is None:
            self._run_headless()
            return
        pygame.init()
        self.screen = pygame.display.set_mode((self.screen_width, self.screen_height))
        pygame.display.set_caption("Mini FC Emulator (Python)")
        if self.clock is None:
            self.clock = pygame.time.Clock()
        try:
            while True:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        raise KeyboardInterrupt
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        raise KeyboardInterrupt
                self.cpu_step()
                if self.screen is None:
                    raise RuntimeError("渲染窗口初始化失败")
                self.screen.fill((0, 0, 0))
                pygame.display.flip()
                if self.clock is not None:
                    self.clock.tick(60)
        except (KeyboardInterrupt, StopIteration):
            pygame.quit()

    def _run_headless(self) -> None:
        try:
            while True:
                self.cpu_step()
                time.sleep(1 / 120)
        except (KeyboardInterrupt, StopIteration):
            return


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python builtin_fc_emulator.py [rom_path.nes]")
        return 1
    rom_path = sys.argv[1]
    if not os.path.exists(rom_path):
        print(f"ROM 文件不存在：{rom_path}")
        return 1
    fc = MiniFC()
    try:
        fc.load_rom(rom_path)
        fc.run()
        return 0
    except Exception as exc:
        print(f"启动失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
