import wpf

from System.Windows import Window

class About(Window):
    def __init__(self):
        wpf.LoadComponent(self, 'About.xaml')
    
    def Button_Click(self, sender, e):
        self.Close()
