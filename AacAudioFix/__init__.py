import os
import subprocess
import json
from pathlib import Path
from typing import List, Tuple, Dict, Any
from app.core.event import eventmanager, Event
from app.plugins import _PluginBase
from app.schemas.types import EventType


class AacAudioFix(_PluginBase):
    # 插件名称
    plugin_name = "AAC音频增强"
    # 插件描述
    plugin_desc = "整理完成后，为视频增加一条AAC立体声音轨，保持原格式和字幕不变。"
    # 插件图标
    plugin_icon = "icon.png"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "Lingma"
    # 作者主页
    author_url = "https://github.com/jxxghp/MoviePilot"
    # 插件配置项ID前缀
    plugin_config_prefix = "aacaudiofix_"
    # 加载顺序
    plugin_order = 50

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        self._enabled = False
        self._target_dirs = []
        
        if config:
            self._enabled = config.get("enabled", False)
            # 获取用户配置的目录，多个目录用换行或逗号分隔
            dirs = config.get("target_dirs", "")
            if dirs:
                self._target_dirs = [d.strip() for d in dirs.replace("\n", ",").split(",") if d.strip()]

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'target_dirs',
                                            'label': '监控目录',
                                            'placeholder': '每行一个目录，例如：\n/volume1/video/Movies',
                                            'rows': 3
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "target_dirs": ""
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass

    @eventmanager.register(EventType.TransferComplete)
    def handle_transfer_complete(self, event: Event):
        """
        监听媒体整理完成事件
        """
        if not self._enabled:
            return

        event_data = event.event_data
        if not event_data:
            return

        dest_path = event_data.get("dest")
        if not dest_path or not os.path.exists(dest_path):
            return

        # 检查是否在监控目录内
        if self._target_dirs:
            in_monitor = any(str(dest_path).startswith(td) for td in self._target_dirs)
            if not in_monitor:
                return

        self.logger.info(f"🎬 检测到媒体整理完成，开始检查: {dest_path}")
        self._process_path(dest_path)

    def _has_aac_stereo(self, video_path: str) -> bool:
        """检测是否已存在 AAC 立体声轨道"""
        try:
            cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', '-select_streams', 'a', video_path]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
            if result.returncode == 0:
                streams = json.loads(result.stdout).get('streams', [])
                for s in streams:
                    if s.get('codec_name') == 'aac' and s.get('channels') == 2:
                        return True
        except Exception as e:
            self.logger.error(f"检测音频失败: {e}")
        return False

    def _process_file(self, video_path: str):
        """处理单个视频文件，保持格式和字幕"""
        if self._has_aac_stereo(video_path):
            self.logger.debug(f"⏭️ 跳过 (已有AAC立体声): {os.path.basename(video_path)}")
            return

        temp_path = video_path + "_temp"
        suffix = Path(video_path).suffix
        if suffix:
            temp_path += suffix

        # 核心命令：映射所有流，仅对新增的第二条音轨进行AAC编码
        cmd = [
            'ffmpeg', '-i', video_path,
            '-map', '0:v', '-map', '0:a', '-map', '0:s?', '-map', '0:d?',
            '-c', 'copy', 
            '-c:a:1', 'aac', 
            '-ac:a:1', '2', 
            '-b:a:1', '192k',
            '-metadata:s:a:1', 'title=AAC Stereo',
            '-movflags', '+faststart',
            '-y', temp_path
        ]

        try:
            self.logger.info(f"🔄 正在增强音频: {os.path.basename(video_path)}")
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
            
            if result.returncode == 0:
                os.replace(temp_path, video_path)
                self.logger.info(f"✅ 处理成功: {os.path.basename(video_path)}")
            else:
                if os.path.exists(temp_path): os.remove(temp_path)
                self.logger.error(f"❌ 处理失败: {result.stderr[:200]}")
        except Exception as e:
            self.logger.error(f"⚠️ 异常: {e}")
            if os.path.exists(temp_path): os.remove(temp_path)

    def _process_path(self, path: str):
        """递归处理路径"""
        video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm'}
        
        if os.path.isfile(path):
            if Path(path).suffix.lower() in video_exts:
                self._process_file(path)
        elif os.path.isdir(path):
            for root, _, files in os.walk(path):
                for file in files:
                    if Path(file).suffix.lower() in video_exts:
                        self._process_file(os.path.join(root, file))