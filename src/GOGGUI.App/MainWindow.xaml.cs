using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using GOGGUI.Views;

namespace GOGGUI;

public sealed partial class MainWindow : Window
{
    public MainWindow()
    {
        this.InitializeComponent();
        ContentFrame.Navigate(typeof(LibraryView));
    }

    private void ContentFrame_NavigationFailed(object sender, NavigationFailedEventArgs e)
    {
        System.Diagnostics.Debug.WriteLine($"Navigation failed: {e.SourcePageType.Name}");
    }
}
