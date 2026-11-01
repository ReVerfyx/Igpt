#import <UIKit/UIKit.h>
#import <MediaPlayer/MediaPlayer.h>
#import <QuartzCore/QuartzCore.h>

@interface IGPTViewController : UIViewController <UIAlertViewDelegate, UITableViewDataSource, UITableViewDelegate, UITextFieldDelegate>
@property (nonatomic, retain) UISegmentedControl *tabs;
@property (nonatomic, retain) UITextView *output;
@property (nonatomic, retain) UITextView *input;
@property (nonatomic, retain) UITextField *address;
@property (nonatomic, retain) UIImageView *screen;
@property (nonatomic, retain) UITableView *videos;
@property (nonatomic, retain) NSArray *videoItems;
@property (nonatomic, retain) UIButton *sendButton;
@property (nonatomic, retain) UIButton *backButton;
@property (nonatomic, retain) UIButton *upButton;
@property (nonatomic, retain) UIButton *downButton;
@property (nonatomic, retain) UIButton *enterButton;
@property (nonatomic, copy) NSString *base;
@property (nonatomic, copy) NSString *token;
@end

@implementation IGPTViewController
@synthesize tabs,output,input,address,screen,videos,videoItems,sendButton,backButton,upButton,downButton,enterButton,base,token;

- (UIButton *)button:(NSString *)name action:(SEL)sel {
    UIButton *b = [UIButton buttonWithType:UIButtonTypeRoundedRect];
    [b setTitle:name forState:UIControlStateNormal];
    [b addTarget:self action:sel forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:b];
    return b;
}
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = [UIColor colorWithWhite:0.94 alpha:1];
    NSUserDefaults *d = [NSUserDefaults standardUserDefaults];
    self.base = [d stringForKey:@"base"] ?: @"";
    // Never restore SSH passwords or bridge secrets from unencrypted preferences.
    [d removeObjectForKey:@"token"];
    self.token = @"";
    self.tabs = [[[UISegmentedControl alloc] initWithItems:
                  [NSArray arrayWithObjects:@"ChatGPT",@"Codex",@"VPS",@"Browser",@"Video",nil]] autorelease];
    self.tabs.segmentedControlStyle = UISegmentedControlStyleBar;
    self.tabs.selectedSegmentIndex = 0;
    [self.tabs addTarget:self action:@selector(changeTab) forControlEvents:UIControlEventValueChanged];
    [self.view addSubview:self.tabs];
    self.output = [[[UITextView alloc] initWithFrame:CGRectZero] autorelease];
    self.output.editable = NO;
    self.output.font = [UIFont systemFontOfSize:16];
    self.output.text = @"iGPT for iPad 1 / iOS 5.1.1\n\nOpen Settings to set HTTPS domain and access token.";
    [self.view addSubview:self.output];
    self.input = [[[UITextView alloc] initWithFrame:CGRectZero] autorelease];
    self.input.font = [UIFont systemFontOfSize:16];
    self.input.layer.borderColor = [UIColor lightGrayColor].CGColor;
    self.input.layer.borderWidth = 1;
    [self.view addSubview:self.input];
    self.address = [[[UITextField alloc] initWithFrame:CGRectZero] autorelease];
    self.address.borderStyle = UITextBorderStyleRoundedRect;
    self.address.autocorrectionType = UITextAutocorrectionTypeNo;
    self.address.autocapitalizationType = UITextAutocapitalizationTypeNone;
    self.address.keyboardType = UIKeyboardTypeURL;
    self.address.returnKeyType = UIReturnKeyGo;
    self.address.delegate = self;
    self.address.placeholder = @"https://example.com";
    [self.view addSubview:self.address];
    self.screen = [[[UIImageView alloc] initWithFrame:CGRectZero] autorelease];
    self.screen.contentMode = UIViewContentModeScaleToFill;
    self.screen.backgroundColor = [UIColor whiteColor];
    self.screen.userInteractionEnabled = YES;
    [self.screen addGestureRecognizer:[[[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(tapBrowser:)] autorelease]];
    [self.view addSubview:self.screen];
    self.videos = [[[UITableView alloc] initWithFrame:CGRectZero style:UITableViewStylePlain] autorelease];
    self.videos.dataSource = self; self.videos.delegate = self;
    [self.view addSubview:self.videos];
    self.sendButton = [self button:@"Send" action:@selector(send)];
    self.backButton = [self button:@"Back" action:@selector(goBack)];
    self.upButton = [self button:@"Up" action:@selector(goUp)];
    self.downButton = [self button:@"Down" action:@selector(goDown)];
    self.enterButton = [self button:@"Enter" action:@selector(goEnter)];
    [self button:@"Settings" action:@selector(settings)].tag = 100;
    [self button:@"New chat" action:@selector(newChat)].tag = 101;
    [self changeTab];
}
- (void)viewDidAppear:(BOOL)animated {
    [super viewDidAppear:animated];
    // Prompt for the bridge access token at each launch; do not persist it.
    if (![self.token length] && !self.presentedViewController) [self settings];
}
- (BOOL)shouldAutorotateToInterfaceOrientation:(UIInterfaceOrientation)orientation {
    return YES;
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    CGFloat w = self.view.bounds.size.width, h = self.view.bounds.size.height;
    self.tabs.frame = CGRectMake(8,8,w-230,34);
    [self.view viewWithTag:100].frame = CGRectMake(w-216,8,100,34);
    [self.view viewWithTag:101].frame = CGRectMake(w-110,8,102,34);
    self.address.frame = CGRectMake(10,48,w-20,36);
    CGFloat top = self.tabs.selectedSegmentIndex == 3 ? 91 : 50;
    self.output.frame = CGRectMake(10,top,w-20,h-top-106);
    self.screen.frame = CGRectMake(10,top,w-20,h-top-106);
    self.videos.frame = CGRectMake(10,top,w-20,h-top-106);
    self.input.frame = CGRectMake(10,h-99,w-325,91);
    self.sendButton.frame = CGRectMake(w-304,h-99,100,42);
    self.backButton.frame = CGRectMake(w-198,h-99,90,42);
    self.upButton.frame = CGRectMake(w-102,h-99,94,42);
    self.downButton.frame = CGRectMake(w-198,h-51,90,42);
    self.enterButton.frame = CGRectMake(w-102,h-51,94,42);
}
- (void)changeTab {
    NSInteger t = self.tabs.selectedSegmentIndex;
    self.output.hidden = (t >= 3);
    self.screen.hidden = (t != 3);
    self.videos.hidden = (t != 4);
    self.address.hidden = (t != 3);
    self.backButton.hidden = self.upButton.hidden = self.downButton.hidden = self.enterButton.hidden = (t != 3);
    self.input.text = @"";
    self.sendButton.titleLabel.textAlignment = UITextAlignmentCenter;
    [self.sendButton setTitle:(t == 3 ? @"Open" : t == 4 ? @"Search" : @"Send") forState:UIControlStateNormal];
    if (t == 0) self.output.text = @"ChatGPT · via OpenAI API on VPS\n";
    if (t == 1) self.output.text = @"Codex · run prompts on VPS workspace\n";
    if (t == 2) self.output.text = @"VPS terminal · unprivileged user\n";
    [self.view setNeedsLayout];
}
- (void)settings {
    UIAlertView *a = [[[UIAlertView alloc] initWithTitle:@"iGPT connection"
             message:@"VPS HTTPS domain and iGPT access token. NOT the SSH/root password."
             delegate:self cancelButtonTitle:@"Cancel" otherButtonTitles:@"Save",nil] autorelease];
    a.alertViewStyle = UIAlertViewStyleLoginAndPasswordInput;
    UITextField *u = [a textFieldAtIndex:0]; u.placeholder = @"https://your-domain";
    u.text = self.base; u.autocorrectionType = UITextAutocorrectionTypeNo; u.autocapitalizationType = UITextAutocapitalizationTypeNone;
    UITextField *p = [a textFieldAtIndex:1]; p.placeholder = @"Bridge token (not root password)"; p.text = @"";
    a.tag = 900;
    [a show];
}
- (void)alertView:(UIAlertView *)a clickedButtonAtIndex:(NSInteger)idx {
    if (a.tag != 900 || idx != 1) return;
    NSString *url = [[a textFieldAtIndex:0] text];
    NSString *key = [[a textFieldAtIndex:1] text];
    if (![url hasPrefix:@"https://"] || ![key length]) {
        self.output.text = @"Use an HTTPS domain and server token.";
        return;
    }
    self.base = [url stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@"/"]];
    self.token = key;
    [[NSUserDefaults standardUserDefaults] setObject:self.base forKey:@"base"];
    [[NSUserDefaults standardUserDefaults] synchronize];
}
- (void)append:(NSString *)s {
    self.output.text = [self.output.text stringByAppendingFormat:@"\n%@\n", s ?: @""];
    if ([self.output.text length] > 25000)
        self.output.text = [self.output.text substringFromIndex:[self.output.text length]-20000];
    [self.output scrollRangeToVisible:NSMakeRange([self.output.text length],0)];
}
- (void)api:(NSString *)path data:(NSDictionary *)body done:(void (^)(NSDictionary *, NSError *))done {
    if (![self.base hasPrefix:@"https://"] || ![self.token length]) {
        [self append:@"Set HTTPS address and token in Settings"];
        return;
    }
    NSURL *u = [NSURL URLWithString:[self.base stringByAppendingString:path]];
    NSMutableURLRequest *r = [NSMutableURLRequest requestWithURL:u];
    [r setHTTPMethod:@"POST"];
    [r setTimeoutInterval:195];
    [r setValue:self.token forHTTPHeaderField:@"X-Igpt-Token"];
    [r setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    NSError *err = nil;
    NSData *bodyData = [NSJSONSerialization dataWithJSONObject:body options:0 error:&err];
    if (!bodyData) { [self append:@"JSON encoding error"]; return; }
    [r setHTTPBody:bodyData];
    [NSURLConnection sendAsynchronousRequest:r queue:[NSOperationQueue mainQueue]
        completionHandler:^(NSURLResponse *resp, NSData *data, NSError *error) {
            NSDictionary *json = nil;
            if (data) json = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
            if (![json isKindOfClass:[NSDictionary class]]) json = [NSDictionary dictionary];
            if (!error && [(NSHTTPURLResponse *)resp statusCode] >= 400)
                error = [NSError errorWithDomain:@"iGPT" code:[(NSHTTPURLResponse *)resp statusCode]
                    userInfo:[NSDictionary dictionaryWithObject:
                        ([json objectForKey:@"detail"] ?: @"Server request failed") forKey:NSLocalizedDescriptionKey]];
            done(json,error);
        }];
}
- (void)send {
    NSInteger t = self.tabs.selectedSegmentIndex;
    NSString *text = self.input.text ?: @"";
    if (t == 3) {
        NSString *url = self.address.text;
        if (![url length]) url = @"https://example.org";
        [self browserAction:@"open" extras:[NSDictionary dictionaryWithObject:url forKey:@"url"]];
        return;
    }
    if (![text length]) return;
    [self.input resignFirstResponder];
    self.input.text = @"";
    if (t == 4) {
        [self api:@"/video/search" data:[NSDictionary dictionaryWithObject:text forKey:@"text"]
             done:^(NSDictionary *j, NSError *e) {
                 if (e) { [self append:[e localizedDescription]]; return; }
                 self.videoItems = [j objectForKey:@"items"];
                 [self.videos reloadData];
             }];
        return;
    }
    NSString *route = t == 0 ? @"/chat" : t == 1 ? @"/codex" : @"/term";
    [self append:[NSString stringWithFormat:@"> %@", text]];
    [self api:route data:[NSDictionary dictionaryWithObject:text forKey:@"text"]
         done:^(NSDictionary *j, NSError *e) {
            [self append:e ? [e localizedDescription] : [j objectForKey:@"text"]];
         }];
}
- (void)newChat {
    if (self.tabs.selectedSegmentIndex != 0) return;
    [self api:@"/chat/reset" data:[NSDictionary dictionary]
         done:^(NSDictionary *j, NSError *e) { self.output.text = @"New chat\n"; }];
}
- (void)browserAction:(NSString *)action extras:(NSDictionary *)extra {
    NSMutableDictionary *p = [NSMutableDictionary dictionaryWithDictionary:extra];
    [p setObject:action forKey:@"action"];
    [self api:@"/browser/action" data:p done:^(NSDictionary *j, NSError *e) {
        if (e) { self.address.text = [e localizedDescription]; return; }
        self.address.text = [j objectForKey:@"url"];
        [self refreshScreen];
    }];
}
- (void)refreshScreen {
    NSMutableURLRequest *r = [NSMutableURLRequest requestWithURL:
                             [NSURL URLWithString:[self.base stringByAppendingString:@"/browser/screen"]]];
    [r setValue:self.token forHTTPHeaderField:@"X-Igpt-Token"];
    [r setCachePolicy:NSURLRequestReloadIgnoringLocalCacheData];
    [NSURLConnection sendAsynchronousRequest:r queue:[NSOperationQueue mainQueue]
        completionHandler:^(NSURLResponse *resp, NSData *data, NSError *error) {
            if (!error && [(NSHTTPURLResponse *)resp statusCode] == 200)
                self.screen.image = [UIImage imageWithData:data];
        }];
}
- (void)tapBrowser:(UITapGestureRecognizer *)tap {
    CGPoint p = [tap locationInView:self.screen];
    if (self.screen.bounds.size.width < 1 || self.screen.bounds.size.height < 1) return;
    int x = (int)(1024.0 * p.x / self.screen.bounds.size.width);
    int y = (int)(640.0 * p.y / self.screen.bounds.size.height);
    [self browserAction:@"click" extras:[NSDictionary dictionaryWithObjectsAndKeys:
        [NSNumber numberWithInt:x],@"x",[NSNumber numberWithInt:y],@"y",nil]];
}
- (BOOL)textFieldShouldReturn:(UITextField *)field {
    [field resignFirstResponder]; [self send]; return YES;
}
- (void)goBack { [self browserAction:@"back" extras:[NSDictionary dictionary]]; }
- (void)goUp { [self browserAction:@"scroll" extras:[NSDictionary dictionaryWithObject:[NSNumber numberWithInt:-440] forKey:@"delta"]]; }
- (void)goDown { [self browserAction:@"scroll" extras:[NSDictionary dictionaryWithObject:[NSNumber numberWithInt:440] forKey:@"delta"]]; }
- (void)goEnter {
    if ([self.input.text length]) {
        NSString *s = self.input.text; self.input.text = @"";
        [self api:@"/browser/action" data:[NSDictionary dictionaryWithObjectsAndKeys:
          @"type",@"action",s,@"text",nil]
         done:^(NSDictionary *j, NSError *e) { [self browserAction:@"enter" extras:[NSDictionary dictionary]]; }];
    } else {
        [self browserAction:@"enter" extras:[NSDictionary dictionary]];
    }
}
- (NSInteger)tableView:(UITableView *)t numberOfRowsInSection:(NSInteger)section {
    return [self.videoItems count];
}
- (UITableViewCell *)tableView:(UITableView *)t cellForRowAtIndexPath:(NSIndexPath *)index {
    UITableViewCell *cell = [t dequeueReusableCellWithIdentifier:@"video"];
    if (!cell) cell = [[[UITableViewCell alloc] initWithStyle:UITableViewCellStyleDefault reuseIdentifier:@"video"] autorelease];
    cell.textLabel.text = [[self.videoItems objectAtIndex:index.row] objectForKey:@"title"];
    cell.textLabel.font = [UIFont systemFontOfSize:15];
    return cell;
}
- (void)tableView:(UITableView *)t didSelectRowAtIndexPath:(NSIndexPath *)index {
    NSString *vid = [[self.videoItems objectAtIndex:index.row] objectForKey:@"id"];
    [self api:@"/video/url" data:[NSDictionary dictionaryWithObject:vid forKey:@"id"]
        done:^(NSDictionary *j, NSError *e) {
            if (e) { self.output.text = [e localizedDescription]; return; }
            NSURL *u = [NSURL URLWithString:[j objectForKey:@"url"]];
            MPMoviePlayerViewController *player = [[[MPMoviePlayerViewController alloc] initWithContentURL:u] autorelease];
            [self presentMoviePlayerViewControllerAnimated:player];
        }];
}
- (void)dealloc {
    [tabs release]; [output release]; [input release]; [address release]; [screen release];
    [videos release]; [videoItems release]; [sendButton release]; [backButton release];
    [upButton release]; [downButton release]; [enterButton release];
    [base release]; [token release]; [super dealloc];
}
@end

@interface IGPTAppDelegate : NSObject <UIApplicationDelegate>
@property (nonatomic, retain) UIWindow *window;
@end
@implementation IGPTAppDelegate
@synthesize window;
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    self.window = [[[UIWindow alloc] initWithFrame:[[UIScreen mainScreen] bounds]] autorelease];
    IGPTViewController *controller = [[[IGPTViewController alloc] init] autorelease];
    self.window.rootViewController = controller;
    [self.window makeKeyAndVisible];
    return YES;
}
- (void)dealloc { [window release]; [super dealloc]; }
@end

int main(int argc, char **argv) {
    NSAutoreleasePool *pool = [[NSAutoreleasePool alloc] init];
    int result = UIApplicationMain(argc, argv, nil, @"IGPTAppDelegate");
    [pool release];
    return result;
}
