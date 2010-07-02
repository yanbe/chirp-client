import cStringIO
import datetime
import glib
import gobject
import gtk
import gtk.glade
import Image
import ImageFileIO
import json
import pango
import pprint
import pygtk
import re
import rfc822
import sys
import threading
import time
import urllib
import urllib2
import webbrowser
pygtk.require('2.0')

loader = gtk.gdk.PixbufLoader()
blankImage = Image.new('RGB', (1,1), (255,255,255))
buf = cStringIO.StringIO()
blankImage.save(buf, format='PNG')
loader.write(buf.getvalue())
loader.close()
blankIcon = loader.get_pixbuf()


class memoize(object):
    def __init__(self, func):
        self._cache = {}
        self._func = func
    
    def __call__(self, *args):
        if args not in self._cache:
            self._cache[args] = self._func(*args)
        return self._cache[args]

class UrlOpenThread(threading.Thread):
    def __init__(self, url):
        threading.Thread.__init__(self)
        self.url = url 
        self.contents = None
        self.error = None

    def run(self):
        try:
            f = urllib2.urlopen(self.url)
            self.contents = f.read()
        except (urllib2.HTTPError, urllib2.URLError, ValueError) as e:
            print e, self.url
            self.error = e
    
    def getContents(self):
        return self.contents
    
    def getError(self):
        return self.error

@memoize
def getStatus(status_id):
    t = UrlOpenThread('http://twitter.com/statuses/show/%s.json' %  status_id)
    t.start()
    while t.isAlive():
        gtk.main_iteration()
    #t.join()
    if t.getError()==None:
        return json.loads(t.getContents())
    else:
        return None

def quoteUnicodeURL(unicodeURL):
    sep_pos = unicodeURL.rindex('/')
    path = unicodeURL[:sep_pos+1]
    filename = unicodeURL[sep_pos+1:]
    quotedURL = path+urllib.quote(filename.encode('utf-8'))
    return quotedURL

@memoize
def getPixbufFromIconURL(profile_image_url):
    try:
        f = urllib2.urlopen(quoteUnicodeURL(profile_image_url))
    except (urllib2.URLError, IOError) as e:
        print e
        return blankIcon
    loader = gtk.gdk.PixbufLoader()
    buf = cStringIO.StringIO()
    image = Image.open(ImageFileIO.ImageFileIO(f))
    if image.mode=='CMYK':
        image = image.convert('RGB')
    image.thumbnail((48, 48))
    image.save(buf, format='PNG')
    loader.write(buf.getvalue())
    try:
        loader.close()
        return loader.get_pixbuf()
    except gobject.GError as e:
        print e
        return blankIcon

def toLocalTime(created_at, fmt="%m/%d %H:%M:%S"):
    datetime_tuple = rfc822.parsedate(created_at)
    d = datetime.datetime(*(datetime_tuple[:-2]))
    return (d+datetime.timedelta(hours=9)).strftime(fmt)

def markupStatus(status, event=None, screen_name_container='user'):
    markup = '' if event!='unfavorite' else '[u]'
    text = glib.markup_escape_text(status['text'])
    def markupRepl(matchobj):
        return '<span foreground="blue">%s </span>' % matchobj.group(0)
    text = re.sub('\S+://\S+', markupRepl, text)
    markup += '<b>%s</b> %s' % (status[screen_name_container]['screen_name'],
        text)
        
    timestamp = toLocalTime(status['created_at'])
    
    markup += ' <span foreground="darkgrey" size="small">%s' % timestamp
    if 'source' in status:
        source = status['source']
        match = re.search('>(.+)<', source)
        if match:
            source = match.group(1)
        markup += ' via %s' % source
    markup += '</span>'
    return markup
    
def markupUserInfo(user):
    markup = '<b>%s</b> (following: %s)' % (user['screen_name'], not user['following'])
    if user['name']:
        markup += '\n<b>Name</b> %s' % glib.markup_escape_text(user['name'])
    if user['location']:
        markup += '\n<b>Location</b> %s' % glib.markup_escape_text(user['location'])
    if user['url']:
        markup += '\n<b>Web</b> <span foreground="blue">%s</span>' % \
             glib.markup_escape_text(user['url'])
    if user['description']:
        markup += '\n<b>Bio</b> %s' % glib.markup_escape_text(user['description'])
    
    markup += '\n<b>Following</b> %s <b>Followers</b> %s' % (
        user['friends_count'], user['followers_count'])
    if 'statuses_count' in user:
        markup += '\n<b>Tweets</b> %s' % user['statuses_count']
    if 'favourites_count' in user:
        markup += '\n<b>Favorites</b> %s' % user['favourites_count']
    markup += '\n<b>Since</b> %s' % toLocalTime(user['created_at'],
        fmt='%Y/%m/%d %H:%M:%S')
    
    return markup

def markupListInfo(chunk):
    prefixMap = {'list_member_added': '[a]', 'list_member_removed': '[r]',
        'list_created': '[c]', 'list_updated': '[up]', 'list_destroyed': '[d]',
        'list_user_subscribed': '[s]', 'list_user_unsubscribed':  '[un]'}
    markup = prefixMap[chunk['event']]
    markup += '<b>%s</b>' % chunk['target_object']['full_name']
    if chunk['target_object']['description']:
        markup += '\n<b>Description</b> %s' % \
            glib.markup_escape_text(chunk['target_object']['description'])
    markup += '\n<b>Members</b> %s' % chunk['target_object']['member_count']
    markup += ' <b>Subscribers</b> %s' % \
        chunk['target_object']['subscriber_count']

    markup += ' <span foreground="grey" size="small">%s %s</span>' % (
        chunk['target']['screen_name'],chunk['event'][5:])
    return markup

def createRow(chunk):
    if 'text' in chunk:
        icon = getPixbufFromIconURL(chunk['user']['profile_image_url'])
        icon.set_data('status', chunk)
        icon.set_data('user', chunk['user'])
        markup = markupStatus(chunk)
        return [icon, markup]
    elif 'delete' in chunk:
        if 'status' in chunk['delete']:
            status_id = chunk['delete']['status']['id']
            if (status_id,) in getStatus._cache:
                return createRow(getStatus(status_id))
            else:
                return [blankIcon, '(<i>tweet not in cache is deleted</i>)']
        else:
            print 'unknown delete event'
            pprint.pprint(chunk)
    elif 'direct_message' in chunk:
        chunk = chunk['direct_message']
        icon_source = getPixbufFromIconURL(chunk['sender']['profile_image_url'])
        icon_source.set_data('user', chunk['sender'])
        icon_target = getPixbufFromIconURL(chunk['recipient']['profile_image_url'])
        icon_target.set_data('user', chunk['recipient'])
        markup = markupStatus(chunk, screen_name_container='sender')
        return [icon_source, icon_target, markup]
    elif 'event' in chunk:
        icon_source = getPixbufFromIconURL(chunk['source']['profile_image_url'])
        icon_source.set_data('user', chunk['source'])
        icon_target = getPixbufFromIconURL(chunk['target']['profile_image_url'])
        icon_target.set_data('user', chunk['target'])
        if chunk['event'] in ('favorite', 'unfavorite', 'retweet'):
            markup = markupStatus(chunk['target_object'], event=chunk['event'])
            icon_source.set_data('status', chunk['target_object'])
        elif chunk['event']=='follow':
            markup = markupUserInfo(chunk['target'])
        elif chunk['event'].startswith('list_'):
            markup = markupListInfo(chunk)
        return [icon_source, icon_target, markup]
    else:
        print 'unknown chunk'
        pprint.pprint(chunk)

def markTabUnread(view):
    scrolledWindow = view.get_parent()
    notebook = scrolledWindow.get_parent()
    if notebook.get_current_page()!=notebook.page_num(scrolledWindow) or \
        scrolledWindow.get_vadjustment().get_value() > 0.0:
        label = notebook.get_tab_label(scrolledWindow)
        text = label.get_text()
        if not text.startswith('<b>'):
            label.set_markup('<b>%s</b>' % text)
    

class ChirpStreamThread(threading.Thread):
    def __init__(self, homeView, replyView, deleteView, dmView, favoriteView,
        retweetView, followView, listView):
        threading.Thread.__init__(self)
        self.homeView = homeView
        self.replyView = replyView
        self.deleteView = deleteView
        self.dmView = dmView
        self.eventViewMap = {'favorite': favoriteView, 
            'retweet': retweetView,'follow': followView, 
            'unfavorite': favoriteView,'list_created': listView,
            'list_member_added': listView, 'list_member_removed': listView,
            'list_updated': listView, 'list_destroyed': listView,
            'list_user_subscribed': listView, 'list_user_unsubscribed': listView}
        self.terminate = False

    def run(self):
        chirpStream = None
        while chirpStream==None:
            try:
                chirpStream = urllib2.urlopen(
                    'http://chirpstream.twitter.com/2b/user.json')
            except (urllib2.HTTPError, urllib2.URLError) as e:
                print e
                time.sleep(3)
        friends = json.loads(chirpStream.next())
        chirpStream.next() #skip blank line
        for line in chirpStream:
            try:
                chunk = json.loads(line)
            except ValueError as e:
                print e
                continue
            row = createRow(chunk)
            if 'text' in chunk:
                getStatus._cache[(chunk['id'],)] = chunk
                if chunk['in_reply_to_status_id'] or \
                    re.findall('@\w+', chunk['text']):
                    targetView = self.replyView
                else:
                    targetView = self.homeView
            elif 'delete' in chunk:
                targetView = self.deleteView
            elif 'direct_message' in chunk:
                targetView = self.dmView
            elif 'event' in chunk:
                targetView = self.eventViewMap[chunk['event']]
            else:
                pprint.pprint(chunk)
            if self.terminate:
                return
            
            if targetView==self.replyView:
                lastRow = targetView.props.model.prepend(None, row)
                targetView.props.model.append(lastRow, [blankIcon, 
                    chunk['in_reply_to_status_id']])
            else:
                targetView.props.model.prepend(row)
                
            markTabUnread(targetView)

def resize_wrap(scroll, allocation):
    view = scroll.get_child()
    column = view.get_columns()[-1]
    renderer = column.get_cell_renderers()[0]
#    renderer.props.wrap_width = column.get_width()
    renderer.props.wrap_width = column.get_width()-renderer.props.xpad*2-view.style_get_property('horizontal-separator')*2

def getUserTimeline(screen_name, max_id):
    s = 'http://api.twitter.com/1/statuses/user_timeline/%s.json?max_id=%s' % (
        screen_name, max_id)
    t = UrlOpenThread(s)
    t.start()
    while t.isAlive():
        gtk.main_iteration()
    if t.getError()!=None:
        raise t.getError()
    timeline = json.loads(t.getContents())
    for chunk in timeline:
        getStatus._cache[(chunk['id'],)] = chunk
    return timeline
    
def guessInReplyToStatusIds(source_status):
    in_reply_to_status_ids = []
    for screen_name in re.findall('@\w+', source_status['text']):
        screen_name = screen_name[1:]
        content_start = source_status['text'].find(screen_name)+len(screen_name)+2
        snippet = source_status['text'][content_start:content_start+3]
        timeline = getUserTimeline(screen_name, source_status['id'])
        for target_status in timeline:
            if target_status['text'].find(snippet) > -1 and \
                    source_status['user']['screen_name'] != screen_name:
                in_reply_to_status_ids.append(target_status['id'])
                break
        else:
            in_reply_to_status_ids.extend(
                [guessed_status['id'] for guessed_status in timeline[0:3]])
    return in_reply_to_status_ids

def expand_conversation(homeView, iter, path, maxExpand=8):
    homeStore = homeView.props.model
    loadingIter = homeStore.iter_nth_child(iter, 0)
    tempRow = homeStore[path].iterchildren().next()
    in_reply_to_status_ids = []
    source_status = homeStore[path][0].get_data('status')
    if source_status['in_reply_to_status_id']:
        in_reply_to_status_ids.append(source_status['in_reply_to_status_id'])
    tempRow[1] = '<i>Loading...</i>'
    inserted_status_ids = set()
    if not in_reply_to_status_ids:
        in_reply_to_status_ids.extend(guessInReplyToStatusIds(source_status))
    while in_reply_to_status_ids and len(inserted_status_ids)<maxExpand:
        in_reply_to_status_id = in_reply_to_status_ids.pop(0)
        if in_reply_to_status_id in inserted_status_ids: 
            continue
        in_reply_to_status = getStatus(in_reply_to_status_id)
        if in_reply_to_status != None:
            row = createRow(in_reply_to_status)
            homeStore.insert_before(iter, loadingIter, row)
            if in_reply_to_status['in_reply_to_status_id'] != None:
                in_reply_to_status_ids.append(
                    in_reply_to_status['in_reply_to_status_id'])
            else:
                in_reply_to_status_ids.extend(
                    guessInReplyToStatusIds(in_reply_to_status))
        
        else:
            row = [blankIcon, '(<i>protected or deleted tweet</i>)']
            homeStore.insert_before(iter, loadingIter, row)

        inserted_status_ids.add(in_reply_to_status_id)

    homeStore.remove(loadingIter)

def terminate_chirp(window, chirp):
    chirp.terminate = True
    chirp.join()
    sys.exit()

def extractURLs(text):
    return [url for url in re.findall('\S+://\S+', text)]

def onRowActivated(treeView, path, view_column, gladeObject):
    row = treeView.props.model[path]
    rendererType = type(view_column.get_cell_renderers()[0])
    if rendererType==gtk.CellRendererText:
        text = row[-1]
        for url in extractURLs(text):
            webbrowser.open(url)
    elif rendererType==gtk.CellRendererPixbuf:
        userInfoView = gladeObject.get_widget('userInfoView')
        if not userInfoView.props.model:
          userInfoView = initTreeView(gladeObject, 'userInfo',
          (('icon', gtk.gdk.Pixbuf), ('status', gobject.TYPE_STRING)))
        else:
          userInfoView.props.model.clear()
        target_column = treeView.get_columns().index(view_column)
        user = row[target_column].get_data('user')
        icon = getPixbufFromIconURL(user['profile_image_url'])
        userInfoView.props.model.append([icon, markupUserInfo(user)])

        userTimelineWindow = gladeObject.get_widget('userTimelineWindow')
        userTimelineWindow.props.title = user['screen_name']
        userTimelineWindow.show()
        
        userTimelineView = gladeObject.get_widget('userTimelineView')
        if not userTimelineView.props.model:
          userTimelineView = initTreeView(gladeObject, 'userTimeline',
            (('icon', gtk.gdk.Pixbuf), ('status', gobject.TYPE_STRING)))
        else:
          userTimelineView.props.model.clear()

        source_status = row[0].get_data('status')
        timeline = getUserTimeline(user['screen_name'], source_status['id'])
        for target_status in timeline:
          userTimelineView.props.model.append(createRow(target_status))


def onMenuActivated(item, text, status, user):
    if text=='Reply':
        newStatus = '@%s ' % status['user']['screen_name']
        statusView.get_buffer().insert_at_cursor(newStatus)
        statusView.set_data('in_reply_to_status_id', status['id'])
        statusView.grab_focus()
        return

    if text=='Retweet':
        u = 'http://api.twitter.com/1/statuses/retweet/%s.json' % status['id']
    elif text=='Favorite':
        u = 'http://api.twitter.com/1/favorites/create/%s.json' % status['id']
    elif text=='Follow':
        u = 'http://api.twitter.com/1/friendships/create/%s.json' % user['id']
    try:
        f = urllib2.urlopen(u, data='')
    except urllib2.HTTPError as e:
        print e
    else:
        j = json.load(f)

def onButtonPressed(treeview, event, statusPopupMenu):
    if event.button == 3:
        x = int(event.x)
        y = int(event.y)
        time = event.time
        pthinfo = treeview.get_path_at_pos(x, y)
        if pthinfo is not None:
            path, column, cellx, celly = pthinfo
            target_column = treeview.get_columns().index(column)
            status = treeview.props.model[path][0].get_data('status')
            cell = treeview.props.model[path][target_column]
            user = cell.get_data('user') if type(cell)==gtk.gdk.Pixbuf else None
            treeview.grab_focus()
            treeview.set_cursor(path, column, 0)
            statusPopupMenu.popup(None, None, None, event.button, time)
            for menuItem in statusPopupMenu.get_children():
                menuItem.connect('activate', onMenuActivated, 
                    menuItem.props.label, status, user)
            statusPopupMenu.show_all()

def onQueryTooltip(treeview, x, y, keyboard_mode, tooltip):
    pthinfo = treeview.get_path_at_pos(x, y)
    if pthinfo is not None:
        path, column, cellx, celly = pthinfo
        if type(column.get_cell_renderers()[0])==gtk.CellRendererPixbuf:
            target_column = treeview.get_columns().index(column)
            user = treeview.props.model[path][target_column].get_data('user')
            if user:
                tooltip.set_markup(markupUserInfo(user))
                tooltip.set_icon(getPixbufFromIconURL(user['profile_image_url']))
                return True
            else:
                return False
    else:
        return False

def initTreeView(gladeObject, viewNamePrefix, columnNameTypePairs,
        modelType=gtk.ListStore):
    store = modelType(*map(lambda pair: pair[1], columnNameTypePairs))
    view = gladeObject.get_widget(viewNamePrefix+'View')
    view.set_model(store)
    for index, (columnName, columnType) in enumerate(columnNameTypePairs):
        if columnType==gtk.gdk.Pixbuf:
            renderer = gtk.CellRendererPixbuf()
            #renderer.set_fixed_size(48, 48)
            renderer.props.yalign = 0
            column = gtk.TreeViewColumn(columnName, renderer, pixbuf=index)
            #min_width = 48+renderer.props.xpad*2 + \
            #    view.style_get_property('horizontal-separator')*2
            #column.set_min_width(min_width)
               
        elif columnType==gobject.TYPE_STRING:
            renderer = gtk.CellRendererText()
            renderer.props.yalign = 0
            renderer.props.wrap_mode = pango.WRAP_WORD
            column = gtk.TreeViewColumn(columnName, renderer, markup=index)
            column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
            
        view.append_column(column)

    scroll = gladeObject.get_widget(viewNamePrefix+'Scroll')
    if scroll:
        scroll.connect_after('size-allocate', resize_wrap)
        scroll.connect('scroll-event', onWheelScroll)
    #scroll.get_vscrollbar().connect('adjust-bounds', onCursorScroll)
#    scroll.get_vscrollbar().connect('value-changed', onValueChanged)
    userTimelineWindow = gladeObject.get_widget('userTimelineWindow')
    view.connect('row-activated', onRowActivated, gladeObject)
    statusView = gladeObject.get_widget('statusView')
    statusPopupMenu = gladeObject.get_widget('statusPopupMenu')
    view.connect('button-press-event', onButtonPressed, statusPopupMenu)
    view.connect('query-tooltip', onQueryTooltip)
    return view


def initAccountInfo(dialog, response_id, gladeObject):
    if response_id==-4:
        sys.exit()
    username = gladeObject.get_widget('usernameEntry').get_text()
    password = gladeObject.get_widget('passwordEntry').get_text()
    topLevelUrls = 'chirpstream.twitter.com', 'api.twitter.com', 'twitter.com'

    passman = urllib2.HTTPPasswordMgrWithDefaultRealm()
    for topLevelUrl in topLevelUrls:
        passman.add_password(None, topLevelUrl, username, password)
    authHandler = urllib2.HTTPBasicAuthHandler(passman)
    opener = urllib2.build_opener(authHandler)
    urllib2.install_opener(opener)
    dialog.destroy()

def addTrackTab(button, searchEntry, trackNotebook):
    treeView = gtk.TreeView()
    treeView.show()
    trackNotebook.append_page(treeView, gtk.Label(searchEntry.get_text()))
    trackNotebook.set_current_page(-1)
    

def onSwitchTab(notebook, page, pagenum):
    scrolledWindow = notebook.get_nth_page(pagenum)
    if scrolledWindow.get_vadjustment().get_value()==0.0:
        label = notebook.get_tab_label(scrolledWindow)
        label.set_markup(label.get_text())

def onWheelScroll(scrolledWindow, event):
    if event.direction==gtk.gdk.SCROLL_UP and \
            scrolledWindow.get_vadjustment().get_value()==0.0:
        notebook = scrolledWindow.get_parent()
        if type(notebook)==gtk.Notebook:
          label = notebook.get_tab_label(scrolledWindow)
          label.set_markup(label.get_text())

def onValueChanged(scrollBar):
    if scrollBar.get_value()==0.0:
        scrolledWindow = scrollBar.get_parent()
        notebook = scrolledWindow.get_parent()
        label = notebook.get_tab_label(scrolledWindow)
        label.set_markup(label.get_text())

def onClickTweetButton(tweetButton, statusView):
    params = dict(status=statusView.props.buffer.props.text)
    in_reply_to_status_id = statusView.get_data('in_reply_to_status_id')
    if in_reply_to_status_id:
        params['in_reply_to_status_id'] = in_reply_to_status_id
    f = urllib2.urlopen('http://api.twitter.com/1/statuses/update.json',
        data=urllib.urlencode(params))
    statusView.props.buffer.props.text = ''
    statusView.grab_focus()


def onTabPlaceChange(item, notebook):
    if item.props.label=='Left':
        notebook.set_tab_pos(gtk.POS_LEFT)
    elif item.props.label=='Top':
        notebook.set_tab_pos(gtk.POS_TOP)
    
def main():
    gladeObject = gtk.glade.XML('chirp-client.glade')

    authDialog = gladeObject.get_widget('authDialog')
    authDialog.connect('response', initAccountInfo, gladeObject)
    authDialog.run()


    replyView = initTreeView(gladeObject, 'reply', 
        (('icon', gtk.gdk.Pixbuf),
         ('status', gobject.TYPE_STRING)), modelType=gtk.TreeStore)
         
    initStatusView = lambda prefix: initTreeView(gladeObject, prefix,
        (('icon', gtk.gdk.Pixbuf), ('status', gobject.TYPE_STRING)))    
    homeView = initStatusView('home')
    deleteView = initStatusView('delete')
    
    initEventView = lambda prefix: initTreeView(gladeObject, prefix,
        (('from', gtk.gdk.Pixbuf), ('to', gtk.gdk.Pixbuf), 
        ('status', gobject.TYPE_STRING)))
    dmView = initEventView('dm')
    favoriteView = initEventView('favorite')
    retweetView = initEventView('retweet')
    followView = initEventView('follow')
    listView = initEventView('list')
    
    notebook1 = gladeObject.get_widget('notebook1')
    notebook1.connect('switch-page', onSwitchTab)
    trackNotebook = gladeObject.get_widget('trackNotebook')
    searchEntry = gladeObject.get_widget('searchEntry')
    searchButton = gladeObject.get_widget('searchButton')
    searchButton.connect('clicked', addTrackTab, searchEntry, trackNotebook)
    replyView.connect('row-expanded', expand_conversation)
    
    chirp = ChirpStreamThread(homeView, replyView, deleteView, dmView,
        favoriteView, retweetView, followView, listView)
    mainWindow = gladeObject.get_widget('mainWindow')
    mainWindow.connect('destroy', terminate_chirp, chirp)
    statusView = gladeObject.get_widget('statusView')
    statusView.set_wrap_mode(gtk.WRAP_CHAR)
    tweetButton = gladeObject.get_widget('tweetButton')
    tweetButton.connect('activate', onClickTweetButton, statusView)
    tweetButton.connect('clicked', onClickTweetButton, statusView)
    tabPlaceTop = gladeObject.get_widget('tabPlaceTop')
    tabPlaceLeft = gladeObject.get_widget('tabPlaceLeft')
    tabPlaceTop.connect('activate', onTabPlaceChange, notebook1)
    tabPlaceLeft.connect('activate', onTabPlaceChange, notebook1)
    mainWindow.show()
    gtk.gdk.threads_init()
    chirp.start()
    gtk.main()

if __name__ == '__main__':
    sys.exit(main())
