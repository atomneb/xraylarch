#!/usr/bin/env python
#
from __future__ import print_function
import sys
import os
from functools import partial
import wx
import numpy
import scipy
import matplotlib
import larch

from wxutils import (Button, MenuItem, Choice, Font)

from .readlinetextctrl import ReadlineTextCtrl
from .larchfilling import Filling
from .columnframe import EditColumnFrame
from . import inputhook

from larch_plugins.io import (read_ascii, read_xdi, read_gsexdi,
                              gsescan_group, fix_varname)

FILE_WILDCARDS = "Scan Data Files(*.0*,*.dat,*.xdi)|*.0*;*.dat;*.xdi|All files (*.*)|*.*"

ICON_FILE = 'larch.ico'

def makeColorPanel(parent, color):
    p = wx.Panel(parent, -1)
    p.SetBackgroundColour(color)
    return p

class LarchWxShell(object):
    ps1 = 'Larch>'
    ps2 = ' ... >'
    def __init__(self, wxparent=None,   writer=None, _larch=None,
                 prompt=None, historyfile=None, output=None, input=None):
        self._larch = _larch
        self.textstyle = None

        if _larch is None:
            self._larch  = larch.Interpreter(historyfile=historyfile,
                                             writer=self)
            self._larch.run_init_scripts()

        self.symtable = self._larch.symtable
        self.prompt = prompt
        self.input  = input
        self.output = output
        # if self.output is not None:
        #    self.encoding = sys.stdout.encoding
        #    sys.stdout = self

        self.objtree = wxparent.objtree

        self.set_textstyle(mode='text')
        self._larch("_sys.display.colors['text2'] = {'color': 'blue'}", add_history=False)

        self._larch.add_plugin('wx', wxparent=wxparent)
        self.symtable.set_symbol('_builtin.force_wxupdate', False)
        self.symtable.set_symbol('_sys.wx.inputhook',   inputhook)
        self.symtable.set_symbol('_sys.wx.ping',   inputhook.ping)
        self.symtable.set_symbol('_sys.wx.force_wxupdate', False)
        self.symtable.set_symbol('_sys.wx.wxapp', output)
        self.symtable.set_symbol('_sys.wx.parent', wx.GetApp().GetTopWindow())

        if self.output is not None:
            style = self.output.GetDefaultStyle()
            bgcol = style.GetBackgroundColour()
            sfont = style.GetFont()
            self.textstyle = wx.TextAttr('black', bgcol, sfont)

        self.SetPrompt(True)

        self.flush_timer = wx.Timer(wxparent)
        self.needs_flush = True
        wxparent.Bind(wx.EVT_TIMER, self.onFlushTimer, self.flush_timer)
        self.flush_timer.Start(500)


    def onUpdate(self, event=None):
        symtable = self.symtable
        if symtable.get_symbol('_builtin.force_wxupdate', create=True):
            app = wx.GetApp()
            evtloop = wx.EventLoop()
            while evtloop.Pending():
                evtloop.Dispatch()
            app.ProcessIdle()
        symtable.set_symbol('_builtin.force_wxupdate', False)


    def SetPrompt(self, complete):
        if self.prompt is None:
            return
        sprompt, scolor = self.ps1, '#000075'
        if not complete:
            sprompt, scolor = self.ps2, '#E00075'
        self.prompt.SetLabel(sprompt)
        self.prompt.SetForegroundColour(scolor)
        self.prompt.Refresh()

    def set_textstyle(self, mode='text'):
        if self.output is None:
            return

        display_colors = self._larch.symtable._sys.display.colors
        textattrs = display_colors.get(mode, {'color':'black'})
        color = textattrs['color']
        style = self.output.GetDefaultStyle()
        bgcol = style.GetBackgroundColour()
        sfont = style.GetFont()
        self.textstyle = wx.TextAttr(color, bgcol, sfont)

    def write(self, text, **kws):
        if self.output is None:
            sys.stdout.write(text)
            sys.stdout.flush()
        else:
            pos0 = self.output.GetLastPosition()
            self.output.WriteText(text)
            pos1 = self.output.GetLastPosition()
            self.output.SetStyle(pos0, pos1, self.textstyle)
            self.needs_flush = True

    def flush(self, *args):
        try:
            self.output.SetInsertionPoint(self.output.GetLastPosition())
        except:
            pass
        self.output.Refresh()
        self.output.Update()
        self.needs_flush = False

    def clear_input(self):
        self._larch.input.clear()
        self.SetPrompt(True)

    def onFlushTimer(self, event=None):
        if self.needs_flush:
            self.flush()

    def eval(self, text, add_history=True, **kws):
        if text is None:
            return
        if text.startswith('!'):
            return os.system(text[1:])

        elif text.startswith('help(') and text.endswith(')'):
            topic = text[5:-1]
            parent = self.symtable.get_parentpath(topic)
            self.objtree.ShowNode("%s.%s" % (parent, topic))
            return
        else:
            if add_history:
                self.input.AddToHistory(text)
                self.write(">%s\n" % text)
            ret = self._larch.eval(text, add_history=add_history)
            if self._larch.error:
                self._larch.input.clear()
                self._larch.writer.set_textstyle('error')
                self._larch.show_errors()
                self._larch.writer.set_textstyle('text')
            elif ret is not None:
                self._larch.writer.write("%s\n" % repr(ret))
            try:
                self.objtree.onRefresh()
            except ValueError:
                pass
            self.SetPrompt(self._larch.input.complete)

class LarchPanel(wx.Panel):
    """Larch Input/Output Panel + Data Viewer as a wx.Panel,
    suitable for embedding into apps
    """
    def __init__(self,  parent=None, _larch=None,
                 historyfile='history_larchgui.lar', **kwds):
        self.parent = parent
        if not historyfile.startswith(larch.site_config.usr_larchdir):
            historyfile = os.path.join(larch.site_config.usr_larchdir,
                                       historyfile)

        wx.Panel.__init__(self, parent, -1, size=(750, 725))

        self.splitter = splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        splitter.SetMinimumPaneSize(150)
        self.SetBackgroundColour('#E9EEE0')

        self.objtree = Filling(splitter,  rootLabel='_main')

        self.output = wx.TextCtrl(splitter, -1,  '',
                                  style=wx.TE_MULTILINE|wx.TE_RICH|wx.TE_READONLY)

        self.output.CanCopy()
        self.output.SetInsertionPointEnd()
        # self.output.SetDefaultStyle(wx.TextAttr('black', 'white', sfont))

        splitter.SplitHorizontally(self.objtree, self.output, 0.5)

        ipanel = wx.Panel(self, -1)

        self.prompt = wx.StaticText(ipanel, -1, 'Larch>', size=(65,-1),
                                    style=wx.ALIGN_CENTER|wx.ALIGN_RIGHT)

        self.input = ReadlineTextCtrl(ipanel, -1,  '', size=(525,-1),
                                      historyfile=historyfile, mode='emacs',
                                      style=wx.ALIGN_LEFT|wx.TE_PROCESS_ENTER)

        self.input.Bind(wx.EVT_TEXT_ENTER, self.onText)
        isizer = wx.BoxSizer(wx.HORIZONTAL)
        isizer.Add(self.prompt,  0, wx.BOTTOM|wx.CENTER)
        isizer.Add(self.input,   1, wx.ALIGN_LEFT|wx.ALIGN_CENTER|wx.EXPAND)

        ipanel.SetSizer(isizer)
        isizer.Fit(ipanel)

        opts = dict(flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL|wx.EXPAND, border=2)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(splitter,  1, **opts)
        sizer.Add(ipanel, 0, **opts)

        self.SetSizer(sizer)
        self.larchshell = LarchWxShell(wxparent=self,
                                       _larch = _larch,
                                       historyfile=historyfile,
                                       prompt = self.prompt,
                                       output = self.output,
                                       input  = self.input)

        self.objtree.SetRootObject(self.larchshell.symtable)
        self.larchshell.set_textstyle('text2')
        self.larchshell.write(larch.make_banner())
        self.larchshell.set_textstyle('text')
        root = self.objtree.tree.GetRootItem()
        self.objtree.tree.Expand(root)

    def update(self):
        self.objtree.onRefresh()

    def onText(self, event=None):
        text =  event.GetString()
        self.input.Clear()
        if text.lower() in ('quit', 'exit', 'quit()', 'exit()'):
            self.parent.onExit()
        else:
            wx.CallAfter(self.larchshell.eval, text)

class LarchFrame(wx.Frame):
    def __init__(self,  parent=None, _larch=None,
                 historyfile='history_larchgui.lar',
                 with_inspection=False, exit_on_close=False, **kwds):

        self.with_inspection = with_inspection
        self.parent = parent
        self.historyfile = historyfile
        self.subframes = {}
        self.last_array_sel = {}

        wx.Frame.__init__(self, parent, -1, size=(750, 725),
                          style= wx.DEFAULT_FRAME_STYLE)
        self.SetTitle('LarchGUI')

        sfont = wx.Font(10, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        self.SetFont(sfont)
        sbar = self.CreateStatusBar(2, wx.CAPTION)

        self.SetStatusWidths([-2,-1])
        self.SetStatusText("Larch initializing...", 0)

        self.mainpanel = LarchPanel(parent=self, _larch=_larch,
                                    historyfile=historyfile)

        self.larchshell = self.mainpanel.larchshell
        self._larch = self.larchshell._larch

        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(self.mainpanel, 1,
                  wx.ALIGN_CENTER_VERTICAL|wx.ALL|wx.EXPAND)

        self.SetSizer(sizer)


        if parent is None and exit_on_close:
            self.Bind(wx.EVT_CLOSE,  self.onExit)
        else:
            self.Bind(wx.EVT_CLOSE,  self.onClose)

        self.BuildMenus()

        larchdir = larch.site_config.larchdir
        fico = os.path.join(larchdir, 'icons', ICON_FILE)
        if os.path.exists(fico):
            self.SetIcon(wx.Icon(fico, wx.BITMAP_TYPE_ICO))

        self.Refresh()
        self.SetStatusText("Ready", 0)
        self.Raise()


    def BuildMenus(self):
        fmenu = wx.Menu()
        MenuItem(self, fmenu, "&Read ASCII Data File\tCtrl+O",
                 "Read Data File", self.onReadData)
        MenuItem(self, fmenu, "&Read and Run Larch Script\tCtrl+R",
                 "Read and Execute a Larch Script", self.onRunScript)
        MenuItem(self, fmenu, "&Save Session History\tCtrl+S",
                 "Save Session History to File", self.onSaveHistory)
        MenuItem(self, fmenu, 'Change Working Directory\tCtrl+W',
                 'Change Directory', self.onChangeDir)
        MenuItem(self, fmenu, 'Clear Input\tCtrl+D',
                 'Clear Input', self.onClearInput)

        if self.with_inspection:
            MenuItem(self, fmenu, 'Show wxPython Inspector\tCtrl+I',
                     'Debug wxPython App', self.onWxInspect)
        fmenu.AppendSeparator()
        MenuItem(self, fmenu, 'Close Display', 'Close display', self.onClose)
        if self.parent is None:
            MenuItem(self, fmenu, 'E&xit', 'End program', self.onExit)

        appmenu = wx.Menu()
        _sys = self.larchshell.symtable._sys
        if hasattr(_sys, 'gui_apps'):
            x_apps = _sys.gui_apps.keys()
            for appname in sorted(x_apps):
                label, creator = _sys.gui_apps[appname]

                MenuItem(self, appmenu, label, label,
                         partial(self.show_subframe,
                                 name=appname, creator=creator))

        hmenu = wx.Menu()
        MenuItem(self, hmenu, '&About',
                 'Information about this program',  self.onAbout)

        menuBar = wx.MenuBar()
        menuBar.Append(fmenu, '&File')
        menuBar.Append(appmenu, 'Applications')
        menuBar.Append(hmenu, '&Help')
        self.SetMenuBar(menuBar)


    def onWxInspect(self, event=None):
        wx.GetApp().ShowInspectionTool()

    def onXRFviewer(self, event=None):
        self.larchshell.eval("xrf_plot()")

    def onClearInput(self, event=None):
        self.larchshell.clear_input()

    def onClearInput(self, event=None):
        self.larchshell.clear_input()

    def show_subframe(self, event=None, name=None, creator=None, **opts):
        if name is None or creator is None:
            return
        shown = False
        if name in self.subframes:
            try:
                self.subframes[name].Raise()
                shown = True
            except:
                del self.subframes[name]
        if not shown:
            self.subframes[name] = creator(parent=self,
                                           _larch=self.larchshell._larch,
                                           **opts)
            self.subframes[name].Show()

    def onReadData(self, event=None):
        wildcard = 'Data file (*.dat)|*.dat|All files (*.*)|*.*'
        dlg = wx.FileDialog(self, message='Open Data File',
                            defaultDir=os.getcwd(),
                            wildcard=FILE_WILDCARDS,
                            style=wx.FD_OPEN|wx.FD_CHANGE_DIR)
        dgroup = None
        if dlg.ShowModal() == wx.ID_OK:
            path = os.path.abspath(dlg.GetPath()).replace('\\', '/')
            filedir, filename = os.path.split(path)
            pref = fix_varname((filename + '_'*8)[:8]).replace('.', '_').lower()

            count, maxcount = 1, 9999
            groupname = "%s%3.3i" % (pref, count)
            while hasattr(self.larchshell.symtable, groupname) and count < maxcount:
                count += 1
                groupname = '%s%3.3i' % (pref, count)

            fh = open(path, 'r')
            line1 = fh.readline().lower()
            fh.close()
            reader = read_ascii
            if 'epics stepscan file' in line1:
                reader = read_gsexdi
            elif 'epics scan' in line1:
                reader = gsescan_group
            elif 'xdi' in line1:
                reader = read_xdi

            dgroup = reader(str(path), _larch=self.larchshell._larch)
            dgroup._path = path
            dgroup._filename = filename
            dgroup._groupname = groupname
        dlg.Destroy()
        if dgroup is not None:

            self.show_subframe(name='coledit', event=None,
                               creator=EditColumnFrame,
                               group=dgroup,
                               last_array_sel=self.last_array_sel,
                               read_ok_cb=self.onReadScan_Success)

    def onReadScan_Success(self, datagroup, array_sel):
        """ called when column data has been selected and is ready to be used"""
        self.last_array_sel = array_sel
        filename  = datagroup._filename
        groupname = datagroup._groupname
        setattr(self.larchshell.symtable, groupname, datagroup)
        self.larchshell.flush()

    def onRunScript(self, event=None):
        wildcard = 'Larch file (*.lar)|*.lar|All files (*.*)|*.*'
        dlg = wx.FileDialog(self, message='Open and Run Larch Script',
                            wildcard=wildcard,
                            style=wx.FD_OPEN|wx.FD_CHANGE_DIR)
        if dlg.ShowModal() == wx.ID_OK:
            fout = os.path.abspath(dlg.GetPath())
            path, fname = os.path.split(fout)
            os.chdir(path)
            text = "run('%s')" % fname
            self.larchshell.write(">%s\n" % text)
            # self._larch.input.historAddToHistory(text)
            wx.CallAfter(self.larchshell.eval, text)
        dlg.Destroy()

    def onSaveHistory(self, event=None):
        wildcard = 'Larch file (*.lar)|*.lar|All files (*.*)|*.*'
        deffile = 'history.lar'
        dlg = wx.FileDialog(self, message='Save Session History File',
                            wildcard=wildcard,
                            defaultFile=deffile,
                            style=wx.FD_SAVE|wx.FD_CHANGE_DIR)
        if dlg.ShowModal() == wx.ID_OK:
            fout = os.path.abspath(dlg.GetPath())
            self._larch.input.history.save(fout, session_only=True)
            self.SetStatusText("Wrote %s" % fout, 0)
        dlg.Destroy()

    def onText(self, event=None):
        text =  event.GetString()
        self.larchshell.write(">%s\n" % text)
        self.input.Clear()
        if text.lower() in ('quit', 'exit'):
            self.onExit()
        else:
            self.input.AddToHistory(text)
            wx.CallAfter(self.larchshell.eval, text)


    def onChangeDir(self, event=None):
        dlg = wx.DirDialog(None, 'Choose a Working Directory',
                           defaultPath = os.getcwd(),
                           style = wx.DD_DEFAULT_STYLE)

        if dlg.ShowModal() == wx.ID_OK:
            os.chdir(dlg.GetPath())
        dlg.Destroy()
        return os.getcwd()

    def onAbout(self, event=None):
        about_msg =  """LarchGui:
        %s""" % (larch.make_banner())

        dlg = wx.MessageDialog(self, about_msg,
                               "About LarchGui", wx.OK | wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

    def onClose(self, event=None):
        # sys.stderr.write(" LarchFrame onClose\n")
        try:
            self.Hide()
            self._larch.input.history.save()
            self.larchshell.symtable.get_symbol('_plotter.close_all_displays')()
        except:
            pass

    def onExit(self, event=None):
        # sys.stderr.write(" LarchFrame onExit\n")
        dlg = wx.MessageDialog(None, 'Really Quit?', 'Question',
                               wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        ret = dlg.ShowModal()
        if ret == wx.ID_YES:
            try:
                self._larch.input.history.save()
                self.larchshell.symtable.get_symbol('_plotter.close_all_displays')()
            except:
                pass
            try:
                self.Destroy()
            except:
                pass
            sys.exit()
        else:
            try:
                event.Veto()
            except:
                pass

if __name__ == '__main__':
    app = wx.PySimpleApp()
    f = LarchFrame(None)
    f.Show()
    app.MainLoop()
