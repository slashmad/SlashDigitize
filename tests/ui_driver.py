"""Real GTK widgets and simulated recording on a private display; no hardware."""
import os
from pathlib import Path
import sys
import tempfile
import time
import wave
from unittest.mock import patch
import gi
gi.require_version('Gtk','4.0');gi.require_version('Adw','1')
from gi.repository import Adw,Gio,GLib,Gtk
from slashdigitize.app import DigitizeApplication
from slashdigitize.video.gui import MainWindow
from slashdigitize.audio.app import RecorderPage
from slashdigitize.process import BackendProcess
from slashdigitize.video import capture,vapoursynth_page,vapoursynth_process,edit
patches=[
 patch.object(RecorderPage,'_refresh_devices',lambda *args:None),
 patch.object(capture,'_detect_ffv1_reference_bitrate',lambda:(None,None)),
 patch.object(capture.CapturePage,'refresh_devices',lambda self:None),
 patch.object(vapoursynth_page.VapourSynthPage,'refresh_environment',lambda self:None)]
for module in [capture,edit,vapoursynth_process,vapoursynth_page]:
 if hasattr(module,'_run_command'):
  patches.append(patch.object(module,'_run_command',lambda *a,**kw:(127,'','Disabled in UI test')))
if not os.environ.get('SLASHDIGITIZE_TEST_METADATA'):
 patches.append(patch.object(MainWindow,'refresh',lambda self:None))
for p in patches:p.start()
errors=[];state=0;opened=[];deadline=time.monotonic()+30
folder=tempfile.TemporaryDirectory(prefix='slashdigitize-ui-')
script='''import signal,sys,time,wave
stopped=False
def stop(*args):
 global stopped
 stopped=True
signal.signal(signal.SIGINT,stop)
w=wave.open(sys.argv[1],'wb');w.setnchannels(2);w.setsampwidth(4);w.setframerate(48000)
w.writeframesraw(b'\\0'*800)
print('50% | 60%',file=sys.stderr,flush=True)
while not stopped:time.sleep(.01)
time.sleep(.2)
w.close()
'''
def walk(widget):
 yield widget
 child=widget.get_first_child()
 while child is not None:
  yield from walk(child)
  child=child.get_next_sibling()
def check_wheel_guard(window):
 """Every value control on every page is wheel-guarded; a closed dropdown keeps its value while the page scrolls."""
 from slashdigitize.ui.widgets import forward_scroll,scroll_guard_of
 from slashdigitize.ui.rows import ChoiceRow
 unguarded=[];total=0
 for tab in [window.audio_page,window.capture_page,window.edit_page,window.timelapse_page,window.vapoursynth_process_page,window.vapoursynth_page,window.system_page,window.help_page]:
  root=getattr(tab,'widget',None) or tab
  for wdg in walk(root):
   if isinstance(wdg,(Adw.ComboRow,Gtk.SpinButton,Gtk.Scale,Gtk.DropDown)):
    if isinstance(wdg,Gtk.DropDown) and wdg.get_ancestor(Adw.ComboRow):continue
    total+=1
    if scroll_guard_of(wdg) is None:unguarded.append(type(wdg).__name__)
 assert total>=60 and not unguarded,(total,unguarded)
 capture=window.capture_page.widget
 row=capture.container_combo;adj=row.get_ancestor(Gtk.ScrolledWindow).get_vadjustment()
 adj.set_value(0);before=row.get_active_id()
 assert forward_scroll(scroll_guard_of(row),0,40,row) is True
 assert row.get_active_id()==before,'closed dropdown changed on wheel'
 assert adj.get_upper()<=adj.get_page_size() or adj.get_value()>0,'page did not scroll'
 print(f'Wheel guard: {total} value controls guarded; closed dropdown kept {before!r}',flush=True)
class TestApp(DigitizeApplication):
 def do_activate(self):
  print("Building window",flush=True)
  try:
   window=MainWindow(self)
  except Exception as error:
   errors.append(repr(error));self.quit();return
  self.window=window;window.present()
  audio=window.audio_page.widget;assert audio is not None
  audio.folder_entry.set_text(folder.name)
  fake=patch('slashdigitize.audio.app.BackendProcess',lambda command:BackendProcess([sys.executable,'-u','-c',script,command[-1]]))
  fake.start();patches.append(fake)
  def tick():
   global state
   try:
    assert time.monotonic()<deadline,'UI timeout'
    assert Adw.StyleManager.get_default().get_dark(),'Dark mode required'
    if state == 0:
     assert window.split.get_show_sidebar(), 'Workflow navigation must start visible'
     theme=Gtk.IconTheme.get_for_display(window.get_display())
     assert theme.has_icon('se.slashmad.SlashDigitize'), 'Application icon must resolve'
    if state<8:
     name=['audio','capture','trim','timelapse','vapoursynth','vsrepo','hardware','help'][state]
     window.stack.set_visible_child_name(name);opened.append(name);state+=1
    elif state==8:
     assert window.stack.get_pages().get_n_items()==8
     check_wheel_guard(window)
     # A missing FFmpeg also produces an empty codec list. The persistent
     # warning must remain visible in that common failure state.
     page=window.capture_page.widget
     saved_command,saved_encoders=page._ffmpeg_command,page._encoders
     page._ffmpeg_command=None;page._encoders=[];page._sync_view()
     assert page.capture_banner.get_revealed(),'Missing FFmpeg warning must not require codecs'
     page._ffmpeg_command=['ffmpeg'];page._sync_view()
     assert not page.capture_banner.get_revealed(),'Available FFmpeg must clear the warning'
     page._ffmpeg_command,page._encoders=saved_command,saved_encoders;page._sync_view()
     window.stack.set_visible_child_name('audio')
     busy=[True];window.jobs.register('Simulated capture',lambda:busy[0],capture=True)
     audio.record_button.emit('clicked')
     assert audio.process is None and 'Stop Simulated capture' in audio.status.get_text()
     busy[0]=False
     assert not audio.auto_stop_check.get_active()
     audio._handle_output(None,'99% | 50%\n')
     audio._show_stats(0,0)
     assert not audio.clipped and not audio.meter.any_clip()
     assert audio.clip_pill.get_text()=='None','99% VU must not claim clipping'
     audio._handle_output(None,'100% | 50%\n')
     audio._show_stats(0,0)
     assert audio.clipped and audio.meter.any_clip()
     assert audio.clip_pill.get_text()=='Detected'
     audio.record_button.emit('clicked');assert audio.running;state=9
    elif state==9 and audio.last_vu and audio.last_vu[0]>0:
     window.close();assert window.get_visible() and not window._closed
     window.activate_action('win.close',None);self.activate_action('quit',None)
     assert window.get_visible() and not window._closed
     assert 'Audio recording' in window.shell_status.get_text()
     before=time.monotonic();audio.stop_button.emit('clicked')
     assert time.monotonic()-before<.15 and audio.running;state=10
    elif state==10 and not audio.running and not window._refreshing:
     assert audio.completed_destination and 'Recording saved' in audio.status.get_text()
     assert 'CLIPPING' not in audio.status.get_text() and audio.clip_pill.get_text()=='None'
     with wave.open(str(audio.completed_destination),'rb') as stream:
      assert stream.getnchannels()==2 and stream.getsampwidth()==4 and stream.getnframes()==100
     assert audio.play_button.get_sensitive()
     if os.environ.get('SLASHDIGITIZE_TEST_METADATA'):
      assert window._ffmpeg_command, 'FFmpeg metadata discovery failed'
      assert window._encoders and window._pixel_formats
     window._update_job_status()
     print('PASS: 8 workflows, dark UI, shared capture exclusion, Close/menu/Quit guards, async stop and finalized WAV.',flush=True)
     state=11
     def finish():
      if os.environ.get('SLASHDIGITIZE_SCREENSHOT'):
       try:
        paintable=Gtk.WidgetPaintable.new(window);snapshot=Gtk.Snapshot()
        paintable.snapshot(snapshot,window.get_width(),window.get_height())
        node=snapshot.to_node();assert node is not None
        texture=window.get_renderer().render_texture(node,None)
        texture.save_to_png(os.environ['SLASHDIGITIZE_SCREENSHOT'])
        print('Screenshot saved',flush=True)
       except Exception as error:
        errors.append(f'Screenshot failed: {error}')
      window.close();return GLib.SOURCE_REMOVE
     GLib.timeout_add(300,finish);return GLib.SOURCE_REMOVE

   except Exception as error:
    import traceback;traceback.print_exc()
    errors.append(repr(error))
    if audio.process:audio.process.interrupt()
    window.destroy();self.quit();return GLib.SOURCE_REMOVE
   return GLib.SOURCE_CONTINUE
  GLib.timeout_add(80,tick)
app=TestApp();app.set_flags(Gio.ApplicationFlags.NON_UNIQUE);app.run([])
for p in reversed(patches):p.stop()
folder.cleanup()
if errors:raise AssertionError(errors)
assert state==11,(state,opened)
